from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque


_CONTEXT_FORMAT = "ebus-evidence-context-v1"
_RAW_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class ContextError(ValueError):
    pass


def record_datetime(record: bytes) -> datetime | None:
    if len(record) < 23:
        return None
    try:
        return datetime.strptime(record[:23].decode("ascii"), _RAW_TS_FORMAT)
    except (UnicodeDecodeError, ValueError):
        return None


def context_should_trigger(event: dict[str, Any], context: dict[str, Any]) -> bool:
    when = context.get("when", {})
    if not when:
        return False

    if "value_nonzero" in when:
        requested = bool(when["value_nonzero"])
        if event.get("value_status") != "decoded":
            return False
        value = event.get("value")
        is_nonzero = value not in (0, 0.0, False, None)
        if is_nonzero != requested:
            return False

    if "value_equals" in when and event.get("value") != when["value_equals"]:
        return False

    if "value_not_equals" in when and event.get("value") == when["value_not_equals"]:
        return False

    if "response_equals" in when and event.get("response") != when["response_equals"]:
        return False

    if "response_not_equals" in when and event.get("response") == when["response_not_equals"]:
        return False

    return True


@dataclass(slots=True)
class ContextSession:
    check_id: str
    description: str
    before_seconds: float
    after_seconds: float
    first_trigger_at: datetime
    end_at: datetime
    pre_window_complete: bool
    records: list[bytes] = field(default_factory=list)
    triggers: list[dict[str, Any]] = field(default_factory=list)


class ContextCaptureManager:
    """Keep a bounded raw-record ring and write small trigger context bundles."""

    def __init__(
        self,
        output_dir: str | Path,
        profile: dict[str, Any],
    ):
        self.output_dir = Path(output_dir)
        self.profile = profile
        self.context_checks = {
            check["id"]: check
            for check in profile["checks"]
            if isinstance(check.get("context"), dict)
        }
        self.max_before_seconds = max(
            (
                float(check["context"].get("before_seconds", 0))
                for check in self.context_checks.values()
            ),
            default=0.0,
        )
        self.buffer: Deque[tuple[datetime, bytes]] = deque()
        self.first_observed_at: datetime | None = None
        self.active: dict[str, ContextSession] = {}
        self.completed = 0
        self.triggered = 0
        self._sequence = 0

    @property
    def trigger_check_count(self) -> int:
        return len(self.context_checks)

    def observe(self, record: bytes) -> None:
        timestamp = record_datetime(record)
        if timestamp is None:
            return

        if self.first_observed_at is None:
            self.first_observed_at = timestamp

        for check_id, session in list(self.active.items()):
            if timestamp > session.end_at:
                self._finalize(check_id, complete_after_window=True)

        for session in self.active.values():
            session.records.append(record)

        self.buffer.append((timestamp, record))
        cutoff = timestamp - timedelta(seconds=self.max_before_seconds)
        while self.buffer and self.buffer[0][0] < cutoff:
            self.buffer.popleft()

    def trigger_event(self, event: dict[str, Any]) -> bool:
        check = self.context_checks.get(str(event.get("check_id")))
        if check is None:
            return False
        return self.trigger(check, event)

    def trigger(self, check: dict[str, Any], event: dict[str, Any]) -> bool:
        context = check.get("context")
        if not isinstance(context, dict) or not context_should_trigger(event, context):
            return False

        self.triggered += 1
        timestamp = datetime.strptime(event["timestamp"]["raw"], _RAW_TS_FORMAT)
        before = float(context.get("before_seconds", 0))
        after = float(context.get("after_seconds", 0))
        end_at = timestamp + timedelta(seconds=after)

        trigger = {
            "timestamp": event["timestamp"],
            "source": event.get("source"),
            "target": event.get("target"),
            "pbsb": event.get("pbsb"),
            "request": event.get("request"),
            "response": event.get("response"),
            "value_status": event.get("value_status"),
            "value": event.get("value"),
        }

        session = self.active.get(check["id"])
        if session is not None:
            session.triggers.append(trigger)
            if end_at > session.end_at:
                session.end_at = end_at
            return True

        start_at = timestamp - timedelta(seconds=before)
        records = [
            record
            for record_time, record in self.buffer
            if start_at <= record_time <= timestamp
        ]
        pre_window_complete = (
            self.first_observed_at is not None
            and self.first_observed_at <= start_at
        )

        self.active[check["id"]] = ContextSession(
            check_id=check["id"],
            description=check.get("description", check["id"]),
            before_seconds=before,
            after_seconds=after,
            first_trigger_at=timestamp,
            end_at=end_at,
            pre_window_complete=pre_window_complete,
            records=records,
            triggers=[trigger],
        )
        return True

    def finish(self) -> int:
        for check_id in list(self.active):
            self._finalize(check_id, complete_after_window=False)
        return self.completed

    def _finalize(self, check_id: str, *, complete_after_window: bool) -> None:
        session = self.active.pop(check_id)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        safe_id = _SAFE_ID_RE.sub("_", check_id).strip("_") or "context"
        stamp = session.first_trigger_at.strftime("%Y%m%dT%H%M%S.%f")[:-3]

        while True:
            self._sequence += 1
            stem = f"{stamp}_{safe_id}_{self._sequence:04d}"
            raw_path = self.output_dir / f"{stem}.raw"
            json_path = self.output_dir / f"{stem}.json"
            if not raw_path.exists() and not json_path.exists():
                break

        payload = b"".join(record.rstrip(b"\r\n") + b"\n" for record in session.records)
        raw_temp = raw_path.with_name(raw_path.name + ".tmp")
        raw_temp.write_bytes(payload)
        raw_temp.replace(raw_path)

        metadata = {
            "format": _CONTEXT_FORMAT,
            "profile": self.profile["name"],
            "profile_version": self.profile.get("version", 1),
            "check_id": session.check_id,
            "description": session.description,
            "before_seconds": session.before_seconds,
            "after_seconds": session.after_seconds,
            "pre_window_complete": session.pre_window_complete,
            "post_window_complete": complete_after_window,
            "trigger_count": len(session.triggers),
            "triggers": session.triggers,
            "record_count": len(session.records),
            "raw_file": raw_path.name,
        }
        temp_path = json_path.with_name(json_path.name + ".tmp")
        temp_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(json_path)
        self.completed += 1
