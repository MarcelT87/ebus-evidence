from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ebus_evidence import __version__
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


def _resolve_sources(args: argparse.Namespace) -> list[Path]:
    raw = Path(args.raw)
    if not raw.is_file():
        raise FileNotFoundError(raw)
    return resolve_raw_sources(raw, include_rotated=bool(args.include_rotated))


def _validate_timezones(args: argparse.Namespace) -> None:
    get_timezone(args.source_timezone)
    get_timezone(args.display_timezone)


def _doctor(args: argparse.Namespace) -> int:
    profile_path = Path(args.profile)
    print(f"eBUS Evidence {__version__}")
    print()

    try:
        _validate_timezones(args)
    except TimezoneError as exc:
        print(f"Timezone .............. ERROR ({exc})")
        return 2

    try:
        sources = _resolve_sources(args)
    except FileNotFoundError as exc:
        print(f"Raw file ............. ERROR ({exc})")
        return 2

    print(f"Raw file ............. OK ({sources[-1]})")
    if args.include_rotated:
        if len(sources) > 1:
            print(f"Rotated raw .......... OK ({sources[0]})")
        else:
            print("Rotated raw .......... not present")

    try:
        profile = load_profile(profile_path)
    except ProfileError as exc:
        print(f"Profile .............. ERROR ({exc})")
        return 2
    print(f"Profile .............. OK ({profile['name']})")

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
            print(f"Raw format ........... ERROR ({source}: {exc})")
            return 2
        if not parsed:
            print(
                f"Raw format ........... ERROR "
                f"({source}: {parse_error or 'no complete records found'})"
            )
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
        sources = _resolve_sources(args)
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


def _add_raw_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--raw", required=True, help="path to an ebusd message-mode raw log")
    parser.add_argument(
        "--include-rotated",
        action="store_true",
        help="also read the sibling FILE.old before the active raw log when present",
    )
    parser.add_argument("--profile", required=True, help="path to a YAML evidence profile")
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

    doctor = subparsers.add_parser("doctor", help="check raw log and profile")
    _add_raw_arguments(doctor)
    doctor.set_defaults(func=_doctor)

    analyze = subparsers.add_parser("analyze", help="analyze an existing raw log")
    _add_raw_arguments(analyze)
    analyze.add_argument("--json", help="optional JSON output path")
    analyze.set_defaults(func=_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
