from __future__ import annotations

from typing import Any

from ebus_evidence.models import Frame


def _norm(value: Any) -> str:
    return str(value).strip().lower()


def frame_matches(frame: Frame, rule: dict[str, Any]) -> bool:
    for field in ("source", "target", "pbsb"):
        if field in rule and _norm(getattr(frame, field)) != _norm(rule[field]):
            return False

    if "initiated_by_ebusd" in rule:
        if frame.initiated_by_ebusd is not bool(rule["initiated_by_ebusd"]):
            return False

    request = frame.request.lower()
    if "request" in rule and request != _norm(rule["request"]):
        return False
    if "request_prefix" in rule and not request.startswith(_norm(rule["request_prefix"])):
        return False

    response = (frame.response or "").lower()
    if "response" in rule and response != _norm(rule["response"]):
        return False
    if "response_prefix" in rule and not response.startswith(_norm(rule["response_prefix"])):
        return False

    return True
