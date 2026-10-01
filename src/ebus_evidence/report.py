from __future__ import annotations

from collections import Counter
from typing import Any, Iterable

from ebus_evidence.decoders import DecodeError, decode_value
from ebus_evidence.matching import frame_matches
from ebus_evidence.models import Frame


_MAX_VARIANTS = 20
_MAX_DISTINCT_VALUES = 256


def _new_state(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": check["id"],
        "description": check.get("description", check["id"]),
        "matches": 0,
        "first": None,
        "last": None,
        "response_variants": Counter(),
        "decoded": 0,
        "decode_errors": 0,
        "nonzero": 0,
        "minimum": None,
        "maximum": None,
        "distinct_values": set(),
        "distinct_overflow": False,
    }


def analyze_frames(frames: Iterable[Frame], profile: dict[str, Any]) -> dict[str, Any]:
    checks = profile["checks"]
    states = {check["id"]: _new_state(check) for check in checks}

    total_frames = 0
    for frame in frames:
        total_frames += 1
        for check in checks:
            if not frame_matches(frame, check["match"]):
                continue
            state = states[check["id"]]
            state["matches"] += 1
            state["first"] = state["first"] or frame.timestamp
            state["last"] = frame.timestamp
            state["response_variants"][frame.response or "<none>"] += 1

            value_spec = check.get("value")
            if value_spec is None:
                continue
            try:
                value = decode_value(frame, value_spec)
            except DecodeError:
                state["decode_errors"] += 1
                continue
            state["decoded"] += 1
            if isinstance(value, (int, float)):
                if value != 0:
                    state["nonzero"] += 1
                state["minimum"] = value if state["minimum"] is None else min(state["minimum"], value)
                state["maximum"] = value if state["maximum"] is None else max(state["maximum"], value)
            if len(state["distinct_values"]) < _MAX_DISTINCT_VALUES:
                state["distinct_values"].add(value)
            elif value not in state["distinct_values"]:
                state["distinct_overflow"] = True

    result_checks = []
    for check in checks:
        state = states[check["id"]]
        top_responses = state["response_variants"].most_common(_MAX_VARIANTS)
        distinct_values = sorted(state["distinct_values"], key=lambda value: (str(type(value)), value))
        result_checks.append(
            {
                "id": state["id"],
                "description": state["description"],
                "matches": state["matches"],
                "first": state["first"],
                "last": state["last"],
                "response_variant_count": len(state["response_variants"]),
                "top_responses": [
                    {"response": response, "count": count}
                    for response, count in top_responses
                ],
                "decoded": state["decoded"],
                "decode_errors": state["decode_errors"],
                "nonzero": state["nonzero"],
                "minimum": state["minimum"],
                "maximum": state["maximum"],
                "distinct_values": distinct_values,
                "distinct_values_truncated": state["distinct_overflow"],
            }
        )

    return {
        "format": "ebus-evidence-report-v1",
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "total_frames": total_frames,
        "checks": result_checks,
    }


def format_text(report: dict[str, Any]) -> str:
    lines = [
        "eBUS Evidence",
        f"Profile: {report['profile']} (v{report['profile_version']})",
        f"Parsed frames: {report['total_frames']}",
        "",
    ]
    for check in report["checks"]:
        lines.append(f"[{check['id']}] {check['description']}")
        lines.append(f"  matches: {check['matches']}")
        lines.append(f"  response variants: {check['response_variant_count']}")
        if check["decoded"] or check["decode_errors"]:
            lines.append(f"  decoded: {check['decoded']} (errors: {check['decode_errors']})")
            lines.append(f"  non-zero: {check['nonzero']}")
            lines.append(f"  range: {check['minimum']} .. {check['maximum']}")
            values = check["distinct_values"]
            suffix = " +more" if check["distinct_values_truncated"] else ""
            lines.append(f"  values: {values}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"
