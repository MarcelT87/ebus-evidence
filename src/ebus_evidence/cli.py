from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ebus_evidence import __version__
from ebus_evidence.input.raw_file import RawParseError, iter_frames, parse_record, split_records
from ebus_evidence.profiles.loader import ProfileError, load_profile
from ebus_evidence.report import analyze_frames, format_text


def _doctor(args: argparse.Namespace) -> int:
    raw = Path(args.raw)
    profile_path = Path(args.profile)
    print(f"eBUS Evidence {__version__}")
    print()

    if not raw.is_file():
        print(f"Raw file ............. ERROR ({raw})")
        return 2
    print(f"Raw file ............. OK ({raw})")

    try:
        profile = load_profile(profile_path)
    except ProfileError as exc:
        print(f"Profile .............. ERROR ({exc})")
        return 2
    print(f"Profile .............. OK ({profile['name']})")

    parsed = False
    parse_error = None
    try:
        for record in split_records(raw):
            try:
                parse_record(record)
                parsed = True
                break
            except RawParseError as exc:
                parse_error = str(exc)
    except OSError as exc:
        print(f"Raw format ........... ERROR ({exc})")
        return 2

    if not parsed:
        print(f"Raw format ........... ERROR ({parse_error or 'no complete records found'})")
        return 2
    print("Raw format ........... OK")
    print()
    print("No eBUS adapter access.")
    print("No active ebusd commands.")
    print("No MQTT publishing.")
    print()
    print("Ready.")
    return 0


def _analyze(args: argparse.Namespace) -> int:
    try:
        profile = load_profile(args.profile)
    except ProfileError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    raw = Path(args.raw)
    if not raw.is_file():
        print(f"error: raw file not found: {raw}", file=sys.stderr)
        return 2

    report = analyze_frames(iter_frames(raw), profile)
    print(format_text(report), end="")

    if args.json:
        output = Path(args.json)
        output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        print(f"JSON report: {output}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="ebus-evidence",
        description="Deterministic read-only evidence extraction from ebusd raw logs",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser("doctor", help="check raw log and profile")
    doctor.add_argument("--raw", required=True, help="path to an ebusd message-mode raw log")
    doctor.add_argument("--profile", required=True, help="path to a YAML evidence profile")
    doctor.set_defaults(func=_doctor)

    analyze = subparsers.add_parser("analyze", help="analyze an existing raw log")
    analyze.add_argument("--raw", required=True, help="path to an ebusd message-mode raw log")
    analyze.add_argument("--profile", required=True, help="path to a YAML evidence profile")
    analyze.add_argument("--json", help="optional JSON output path")
    analyze.set_defaults(func=_analyze)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
