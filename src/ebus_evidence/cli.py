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
        label = "host file" if discovery.installation == "docker" else "file"
        print(f"  {label:<20} {discovery.raw_file_host}")
    elif discovery.raw_file_container:
        print("  host file ........... unresolved (no matching Docker mount)")
    if discovery.raw_size_kb is not None:
        print(f"  size limit .......... {discovery.raw_size_kb} kB")


def _doctor(args: argparse.Namespace) -> int:
    print(f"eBUS Evidence {__version__}")
    print()

    try:
        _validate_timezones(args)
    except TimezoneError as exc:
        print(f"Timezone .............. ERROR ({exc})")
        return 2

    discovered: EbusdDiscovery | None = None
    raw_path = args.raw

    if raw_path is None:
        discovered = discover_ebusd()
        if discovered is None:
            print("ebusd ................. not detected")
            print()
            print("Automatic discovery currently supports Docker and native/systemd ebusd.")
            print("Use --raw /path/to/ebusd.raw for a manual check.")
            return 2

        _print_discovery(discovered)

        if not discovered.raw_enabled:
            return 2
        if discovered.raw_mode == "bytes":
            print()
            print("Raw format ............ ERROR (byte-level logging is not supported)")
            print("Use --lograwdata without '=bytes'.")
            return 2
        if discovered.raw_file_host is None:
            print()
            if discovered.installation == "docker":
                print("Raw file .............. ERROR (container path could not be mapped to host)")
                print("Use --raw /host/path/to/ebusd.raw for a manual check.")
            else:
                print("Raw file .............. ERROR (--lograwdatafile was not found)")
                print("Configure an explicit raw-log file or use --raw manually.")
            return 2

        raw_path = discovered.raw_file_host
        print()

    try:
        sources = _resolve_sources(raw_path, bool(args.include_rotated))
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

    try:
        sources = _resolve_sources(args.raw, bool(args.include_rotated))
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
    print(format_text(report), end="")

    if args.json:
        output = Path(args.json)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"JSON report: {output}")
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
    doctor.add_argument("--profile", help="optional YAML evidence profile to validate")
    _add_time_arguments(doctor)
    doctor.set_defaults(func=_doctor)

    analyze = subparsers.add_parser("analyze", help="analyze an existing raw log")
    analyze.add_argument("--raw", required=True, help="path to an ebusd message-mode raw log")
    analyze.add_argument(
        "--include-rotated",
        action="store_true",
        help="also read the sibling FILE.old before the active raw log when present",
    )
    analyze.add_argument("--profile", required=True, help="path to a YAML evidence profile")
    _add_time_arguments(analyze)
    analyze.add_argument("--json", help="optional JSON output path")
    analyze.set_defaults(func=_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
