from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ebus_evidence import __version__
from ebus_evidence.discovery.ebusd import EbusdDiscovery, discover_ebusd
from ebus_evidence.input.raw_file import (
    RawParseError,
    iter_frames_many,
    parse_record,
    resolve_raw_sources,
    split_records,
)
from ebus_evidence.profiles.loader import ProfileError, load_profile
from ebus_evidence.report import analyze_frames, format_text
from ebus_evidence.timeutil import TimezoneError, get_timezone
from ebus_evidence.state import EvidenceStateStore, StateError
from ebus_evidence.watch import ResumeError, run_watch


def _resolve_sources(raw_path: str, include_rotated: bool) -> list[Path]:
    raw = Path(raw_path)
    if not raw.is_file():
        raise FileNotFoundError(raw)
    return resolve_raw_sources(raw, include_rotated=include_rotated)


def _validate_timezones(args: argparse.Namespace) -> None:
    get_timezone(args.source_timezone)
    get_timezone(args.display_timezone)


def _check_raw_sources(sources: list[Path]) -> tuple[bool, str | None]:
    for source in sources:
        parsed = False
        parse_error = None
        try:
            for record in split_records(source):
                try:
                    parse_record(record)
                    parsed = True
                    break
                except RawParseError as exc:
                    parse_error = str(exc)
        except OSError as exc:
            return False, f"{source}: {exc}"
        if not parsed:
            return False, f"{source}: {parse_error or 'no complete records found'}"
    return True, None


def _print_discovery(discovery: EbusdDiscovery) -> None:
    print("ebusd")
    if discovery.installation == "docker":
        print("  detected ............ Docker")
        print(f"  container ........... {discovery.container_name}")
        print(f"  image ............... {discovery.image}")
    else:
        print("  detected ............ native/systemd")
        print(f"  service ............. {discovery.service_name}")
        print(f"  pid ................. {discovery.pid}")

    print()
    print("Raw logging")
    if not discovery.raw_enabled:
        print("  enabled ............. no")
        print()
        print("Recommended ebusd options:")
        print("  --lograwdata")
        if discovery.installation == "docker":
            print("  --lograwdatafile=/rawlog/ebusd.raw")
        else:
            print("  --lograwdatafile=/var/log/ebusd.raw")
        print("  --lograwdatasize=102400")
        print()
        print("No changes were made.")
        return

    print("  enabled ............. yes")
    print(f"  mode ................ {discovery.raw_mode or 'unknown'}")
    if discovery.raw_file_container:
        print(f"  container file ...... {discovery.raw_file_container}")
    if discovery.raw_file_host:
        if discovery.installation == "docker":
            print(f"  host file ........... {discovery.raw_file_host}")
        else:
            print(f"  file ................ {discovery.raw_file_host}")
    elif discovery.raw_file_container:
        print("  host file ........... unresolved (no matching Docker mount)")
    if discovery.raw_size_kb is not None:
        print(f"  size limit .......... {discovery.raw_size_kb} kB")


def _discovered_raw_path() -> tuple[str | None, EbusdDiscovery | None, str | None]:
    discovery = discover_ebusd()
    if discovery is None:
        return None, None, "ebusd was not detected"
    if not discovery.raw_enabled:
        return None, discovery, "ebusd raw logging is not enabled"
    if discovery.raw_mode == "bytes":
        return None, discovery, "ebusd uses byte-level raw logging; message mode is required"
    if discovery.raw_file_host is None:
        if discovery.installation == "docker":
            return None, discovery, "ebusd raw-log container path could not be mapped to the host"
        return None, discovery, "ebusd --lograwdatafile was not found"
    return discovery.raw_file_host, discovery, None


def _doctor(args: argparse.Namespace) -> int:
    print(f"eBUS Evidence {__version__}")
    print()

    try:
        _validate_timezones(args)
    except TimezoneError as exc:
        print(f"Timezone .............. ERROR ({exc})")
        return 2

    raw_path = args.raw

    if raw_path is None:
        raw_path, discovered, error = _discovered_raw_path()
        if discovered is None:
            print("ebusd ................. not detected")
            print()
            print("Automatic discovery currently supports Docker and native/systemd ebusd.")
            print("Use --raw /path/to/ebusd.raw for a manual check.")
            return 2

        _print_discovery(discovered)
        if error:
            print()
            print(f"Raw file .............. ERROR ({error})")
            if discovered.raw_mode == "bytes":
                print("Use --lograwdata without '=bytes'.")
            elif discovered.raw_enabled:
                print("Use --raw /path/to/ebusd.raw for a manual check.")
            return 2
        print()

    try:
        sources = _resolve_sources(str(raw_path), bool(args.include_rotated))
    except FileNotFoundError as exc:
        print(f"Raw file ............. ERROR ({exc})")
        return 2

    print(f"Raw file ............. OK ({sources[-1]})")
    if args.include_rotated:
        if len(sources) > 1:
            print(f"Rotated raw .......... OK ({sources[0]})")
        else:
            print("Rotated raw .......... not present")

    if args.profile:
        try:
            profile = load_profile(args.profile)
        except ProfileError as exc:
            print(f"Profile .............. ERROR ({exc})")
            return 2
        print(f"Profile .............. OK ({profile['name']})")
    else:
        print("Profile .............. not checked")

    raw_ok, raw_error = _check_raw_sources(sources)
    if not raw_ok:
        print(f"Raw format ........... ERROR ({raw_error})")
        return 2

    print("Raw format ........... OK")
    if args.source_timezone:
        print(f"Source timezone ...... OK ({args.source_timezone})")
        if args.display_timezone:
            print(f"Display timezone ..... OK ({args.display_timezone})")
    else:
        print("Source timezone ...... unspecified (raw timestamps preserved)")
    print()
    print("No eBUS adapter access.")
    print("No active ebusd commands.")
    print("No MQTT publishing.")
    print("No configuration changes.")
    print()
    print("Ready.")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    try:
        _validate_timezones(args)
    except TimezoneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    raw_path = args.raw
    discovery: EbusdDiscovery | None = None
    if raw_path is None:
        raw_path, discovery, error = _discovered_raw_path()
        if error:
            print(f"error: cannot auto-discover usable ebusd raw log: {error}", file=sys.stderr)
            print("hint: use --raw /path/to/ebusd.raw to override discovery", file=sys.stderr)
            return 2

    try:
        sources = _resolve_sources(str(raw_path), bool(args.include_rotated))
    except FileNotFoundError as exc:
        print(f"error: raw file not found: {exc}", file=sys.stderr)
        return 2

    report = analyze_frames(
        iter_frames_many(sources),
        profile,
        source_timezone=args.source_timezone,
        display_timezone=args.display_timezone,
    )
    report["source_files"] = [source.name for source in sources]
    report["raw_path"] = str(raw_path)
    report["raw_path_source"] = (
        f"auto:{discovery.installation}" if discovery is not None else "manual"
    )
    print(format_text(report), end="")

    if args.json:
        output = Path(args.json)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"JSON report: {output}")
    return 0



def _watch(args: argparse.Namespace) -> int:
    try:
        _validate_timezones(args)
    except TimezoneError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    raw_path = args.raw
    discovery: EbusdDiscovery | None = None
    if raw_path is None:
        raw_path, discovery, error = _discovered_raw_path()
        if error:
            print(f"error: cannot auto-discover usable ebusd raw log: {error}", file=sys.stderr)
            print("hint: use --raw /path/to/ebusd.raw to override discovery", file=sys.stderr)
            return 2

    print("eBUS Evidence watch")
    print(f"Profile: {profile['name']} (v{profile.get('version', 1)})")
    source = f"auto:{discovery.installation}" if discovery is not None else "manual"
    print(f"Raw path: {raw_path} ({source})")
    print("Mode: follow new records only; Ctrl-C to stop")
    if args.seconds is not None:
        print(f"Duration: {args.seconds:g} seconds")
    if args.source_timezone:
        display = args.display_timezone or args.source_timezone
        print(f"Timestamps: raw source={args.source_timezone}, display={display}")
    else:
        print("Timestamps: raw values, timezone unspecified")

    state_store = None
    if args.reset_checkpoint and not args.state:
        print("error: --reset-checkpoint requires --state", file=sys.stderr)
        return 2

    if args.state:
        try:
            state_store = EvidenceStateStore.open(args.state, profile)
            if args.reset_checkpoint:
                state_store.clear_checkpoint(
                    reason="user acknowledged a resume gap with --reset-checkpoint"
                )
        except StateError as exc:
            print(f"error: cannot open evidence state: {exc}", file=sys.stderr)
            return 2
        print(f"State: {args.state} ({state_store.total_events} existing events)")
        if args.reset_checkpoint:
            print("Checkpoint: reset; continuity gap recorded")
        elif state_store.checkpoint is None:
            print("Checkpoint: none; first run starts at the current raw-log end")
        else:
            print(
                "Checkpoint: "
                f"device={state_store.checkpoint['device']} "
                f"inode={state_store.checkpoint['inode']} "
                f"offset={state_store.checkpoint['offset']}"
            )

    if args.state_flush_interval <= 0:
        print("error: --state-flush-interval must be greater than zero", file=sys.stderr)
        return 2
    if state_store is not None:
        print(f"State flush interval: {args.state_flush_interval:g} seconds")
    if args.context_dir:
        context_checks = sum(
            1 for check in profile["checks"] if isinstance(check.get("context"), dict)
        )
        print(f"Context capture: {args.context_dir} ({context_checks} profile triggers)")
    print()

    try:
        stats = run_watch(
            str(raw_path),
            profile,
            source_timezone=args.source_timezone,
            display_timezone=args.display_timezone,
            seconds=args.seconds,
            poll_interval=args.poll_interval,
            json_lines=args.json_lines,
            state_store=state_store,
            state_flush_interval=args.state_flush_interval,
            context_dir=args.context_dir,
        )
    except ResumeError as exc:
        print(f"error: cannot resume watch safely: {exc}", file=sys.stderr)
        if args.state:
            print(
                "hint: if the missing interval is acceptable, rerun with "
                "--reset-checkpoint to record the continuity gap and start at the current end",
                file=sys.stderr,
            )
        return 2
    except (OSError, StateError) as exc:
        print(f"error: cannot watch raw log: {exc}", file=sys.stderr)
        return 2

    print()
    print(
        f"Watch summary: frames={stats.frames} matches={stats.matches} "
        f"non_frames={stats.non_frame_records} skipped={stats.skipped_records} "
        f"partial_tail={stats.partial_tail} rotations={stats.rotations} "
        f"context_triggers={stats.context_triggers} contexts={stats.context_captures} "
        f"resume={stats.resume_mode}"
    )
    if stats.non_frame_kinds:
        print("Non-frame records:")
        for kind, count in stats.non_frame_kinds.most_common():
            print(f"  {count:>5}  {kind}")
            for sample in stats.non_frame_samples.get(kind, []):
                print(f"         sample: {sample}")
    if stats.skip_reasons:
        print("Skipped record reasons:")
        for reason, count in stats.skip_reasons.most_common():
            print(f"  {count:>5}  {reason}")
            for sample in stats.skip_samples.get(reason, []):
                print(f"         sample: {sample}")
    return 0

def _add_time_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source-timezone",
        help="IANA timezone of raw ebusd timestamps, e.g. UTC or Europe/Berlin",
    )
    parser.add_argument(
        "--display-timezone",
        help="optional IANA timezone used for human-readable timestamps",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ebus-evidence",
        description="Deterministic read-only evidence extraction from ebusd raw logs",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor",
        help="discover/check ebusd raw logging, or validate an explicit raw log",
    )
    doctor.add_argument(
        "--raw",
        help="manual path to an ebusd message-mode raw log; otherwise ebusd is discovered",
    )
    doctor.add_argument(
        "--include-rotated",
        action="store_true",
        help="also read the sibling FILE.old before the active raw log when present",
    )
    doctor.add_argument(
        "--profile",
        help="optional profile path or bundled profile name to validate",
    )
    _add_time_arguments(doctor)
    doctor.set_defaults(func=_doctor)

    analyze = subparsers.add_parser(
        "analyze",
        help="analyze an ebusd raw log; auto-discover it when --raw is omitted",
    )
    analyze.add_argument(
        "--raw",
        help="manual path to an ebusd message-mode raw log; otherwise ebusd is discovered",
    )
    analyze.add_argument(
        "--include-rotated",
        action="store_true",
        help="also read the sibling FILE.old before the active raw log when present",
    )
    analyze.add_argument(
        "--profile",
        required=True,
        help="profile path or bundled profile name, e.g. hw5103-open-evidence",
    )
    _add_time_arguments(analyze)
    analyze.add_argument("--json", help="optional JSON output path")
    analyze.set_defaults(func=_analyze)

    watch = subparsers.add_parser(
        "watch",
        help="follow new ebusd raw-log records and print matching evidence",
    )
    watch.add_argument(
        "--raw",
        help="manual path to an ebusd message-mode raw log; otherwise ebusd is discovered",
    )
    watch.add_argument(
        "--profile",
        required=True,
        help="profile path or bundled profile name, e.g. hw5103-open-evidence",
    )
    watch.add_argument(
        "--seconds",
        type=float,
        help="optional test/runtime limit; omit to watch until Ctrl-C",
    )
    watch.add_argument(
        "--poll-interval",
        type=float,
        default=0.25,
        help="filesystem poll interval in seconds (default: 0.25)",
    )
    watch.add_argument(
        "--json-lines",
        action="store_true",
        help="emit one JSON object per matching event",
    )
    watch.add_argument(
        "--state",
        help="optional compact JSON evidence state and resume checkpoint",
    )
    watch.add_argument(
        "--reset-checkpoint",
        action="store_true",
        help="acknowledge a continuity gap, clear a stale checkpoint, and start at the current raw-log end",
    )
    watch.add_argument(
        "--state-flush-interval",
        type=float,
        default=5.0,
        help="seconds between atomic state/checkpoint writes (default: 5)",
    )
    watch.add_argument(
        "--context-dir",
        help="optional directory for profile-triggered raw context bundles",
    )
    _add_time_arguments(watch)
    watch.set_defaults(func=_watch)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
