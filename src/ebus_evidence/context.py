from __future__ import annotations

import json
import re
from collections import deque
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Deque

from ebus_evidence.structure import StructureLimitError, validate_structure_limits


_CONTEXT_FORMAT = "ebus-evidence-context-v1"
_RAW_TS_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
_SAFE_ID_RE = re.compile(r"[^A-Za-z0-9_.-]+")

# Internal limits: no extra setup or profile-version change is required.
MAX_CONTEXT_SECONDS = 15 * 60
MAX_CONTEXT_BYTES = 4 * 1024 * 1024
MAX_CONTEXT_RECORDS = 10000
MAX_CONTEXT_TRIGGERS = 256
MAX_RING_BYTES = 2 * 1024 * 1024
MAX_RING_RECORDS = 10000


class ContextError(ValueError):
    pass


def validate_capture_metadata(metadata: dict[str, Any]) -> None:
    """Validate additive bounded-capture fields; legacy v1 contexts stay valid."""
    fields = {
        "capture_end_reason", "capture_end_timestamp", "segment_started_at",
        "continuation_of", "capture_limits",
    }
    if not fields.intersection(metadata):
        return
    if not fields.issubset(metadata):
        raise ContextError("bounded context metadata is incomplete")
    reason = metadata["capture_end_reason"]
    reasons = {
        "post_window_complete", "collection_stopped", "clock_regression",
        "duration_limit", "byte_limit", "record_limit", "trigger_limit",
    }
    if not isinstance(reason, str) or reason not in reasons:
        raise ContextError("invalid context capture_end_reason")
    if metadata.get("post_window_complete") is not (reason == "post_window_complete"):
        raise ContextError("context completion flag contradicts capture_end_reason")
    for key in ("capture_end_timestamp", "segment_started_at"):
        value = metadata[key]
        try:
            datetime.strptime(value, _RAW_TS_FORMAT)
        except (ValueError, TypeError) as exc:
            raise ContextError(f"invalid context {key}") from exc
    previous = metadata["continuation_of"]
    if previous is not None:
        if (not isinstance(previous, str) or not previous.endswith(".raw")
                or "/" in previous or "\\" in previous or previous == metadata.get("raw_file")):
            raise ContextError("context continuation_of must reference another safe raw filename")
        if metadata.get("pre_window_complete") is not False:
            raise ContextError("continuation context cannot claim a complete pre-window")
    limits = metadata["capture_limits"]
    keys = {"max_seconds", "max_bytes", "max_records", "max_triggers"}
    if not isinstance(limits, dict) or set(limits) != keys:
        raise ContextError("invalid context capture_limits")
    if any(not isinstance(v, int) or isinstance(v, bool) or v < 1 for v in limits.values()):
        raise ContextError("context capture limits must be positive integers")
    for field_name, limit in (("record_count", "max_records"), ("trigger_count", "max_triggers")):
        count = metadata.get(field_name)
        if not isinstance(count, int) or isinstance(count, bool) or not 0 <= count <= limits[limit]:
            raise ContextError(f"context {field_name} exceeds capture limit")
    triggers = metadata.get("triggers")
    if not isinstance(triggers, list) or len(triggers) != metadata["trigger_count"]:
        raise ContextError("context trigger_count does not match triggers")


@dataclass(frozen=True, slots=True)
class ContextMetadataScope:
    current: tuple[Path, ...]
    historical: tuple[Path, ...]


def context_metadata_scope(
    output_dir: str | Path,
    profile: dict[str, Any],
) -> ContextMetadataScope:
    directory = Path(output_dir)
    if not directory.exists():
        return ContextMetadataScope(current=(), historical=())
    if not directory.is_dir():
        raise ContextError(f"context path is not a directory: {directory}")

    profile_name = profile["name"]
    profile_version = profile.get("version", 1)
    current: list[Path] = []
    historical: list[Path] = []

    for metadata_path in sorted(directory.glob("*.json"), key=lambda path: path.name):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ContextError(
                f"cannot read context metadata {metadata_path.name}: {exc}"
            ) from exc
        except RecursionError as exc:
            raise ContextError(
                f"cannot read context metadata {metadata_path.name}: "
                "structure is too deeply nested"
            ) from exc
        try:
            validate_structure_limits(
                metadata,
                label=f"context metadata {metadata_path.name}",
            )
        except StructureLimitError as exc:
            raise ContextError(str(exc)) from exc

        if (
            not isinstance(metadata, dict)
            or metadata.get("format") != _CONTEXT_FORMAT
        ):
            raise ContextError(
                f"unsupported context metadata: {metadata_path.name}"
            )
        validate_capture_metadata(metadata)
        if metadata.get("profile") != profile_name:
            raise ContextError(
                f"context profile mismatch in {metadata_path.name}: "
                f"{metadata.get('profile')!r} != {profile_name!r}"
            )
        version = metadata.get("profile_version")
        if not isinstance(version, int) or isinstance(version, bool) or version < 1:
            raise ContextError(
                f"context profile version is invalid in {metadata_path.name}"
            )
        if version == profile_version:
            current.append(metadata_path)
        elif version < profile_version:
            historical.append(metadata_path)
        else:
            raise ContextError(
                f"context profile version is newer than active profile in "
                f"{metadata_path.name}: v{version} > v{profile_version}"
            )

    return ContextMetadataScope(
        current=tuple(current),
        historical=tuple(historical),
    )


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
    segment_started_at: datetime
    continuation_of: str | None = None
    raw_bytes: int = 0
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
        self.buffer_bytes = 0
        self.buffer_dropped_through: datetime | None = None
        self.first_observed_at: datetime | None = None
        self.last_observed_at: datetime | None = None
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

        record = record.rstrip(b"\r\n") + b"\n"
        if self.last_observed_at is not None and timestamp < self.last_observed_at:
            # Do not claim complete windows across a backward source-clock jump.
            for check_id in list(self.active):
                self._finalize(check_id, complete_after_window=False,
                               reason="clock_regression", ended_at=timestamp)
            self.buffer.clear()
            self.buffer_bytes = 0
            self.buffer_dropped_through = None
            self.first_observed_at = timestamp
        self.last_observed_at = timestamp

        if self.first_observed_at is None:
            self.first_observed_at = timestamp

        for check_id, session in list(self.active.items()):
            if timestamp > session.end_at:
                self._finalize(check_id, complete_after_window=True,
                               reason="post_window_complete", ended_at=timestamp)
                continue
            reason = None
            if timestamp >= session.segment_started_at + timedelta(seconds=MAX_CONTEXT_SECONDS):
                reason = "duration_limit"
            elif session.raw_bytes + len(record) > MAX_CONTEXT_BYTES:
                reason = "byte_limit"
            elif len(session.records) >= MAX_CONTEXT_RECORDS:
                reason = "record_limit"
            if reason:
                self._continue_segment(check_id, timestamp, reason)

        for session in self.active.values():
            session.records.append(record)
            session.raw_bytes += len(record)

        self.buffer.append((timestamp, record))
        self.buffer_bytes += len(record)
        cutoff = timestamp - timedelta(seconds=self.max_before_seconds)
        while self.buffer and self.buffer[0][0] < cutoff:
            _, removed = self.buffer.popleft()
            self.buffer_bytes -= len(removed)
        while self.buffer and (
            self.buffer_bytes > MAX_RING_BYTES or len(self.buffer) > MAX_RING_RECORDS
        ):
            removed_at, removed = self.buffer.popleft()
            self.buffer_bytes -= len(removed)
            self.buffer_dropped_through = removed_at

    def _continue_segment(self, check_id: str, timestamp: datetime, reason: str) -> None:
        session = self.active[check_id]
        previous = self._finalize(
            check_id, complete_after_window=False, reason=reason, ended_at=timestamp
        )
        self.active[check_id] = replace(
            session,
            segment_started_at=timestamp,
            continuation_of=previous,
            pre_window_complete=False,
            records=[],
            triggers=[],
            raw_bytes=0,
        )

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
            if len(session.triggers) >= MAX_CONTEXT_TRIGGERS:
                self._continue_segment(check["id"], timestamp, "trigger_limit")
                session = self.active[check["id"]]
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
            and (
                self.buffer_dropped_through is None
                or self.buffer_dropped_through < start_at
            )
        )

        self.active[check["id"]] = ContextSession(
            check_id=check["id"],
            description=check.get("description", check["id"]),
            before_seconds=before,
            after_seconds=after,
            first_trigger_at=timestamp,
            end_at=end_at,
            pre_window_complete=pre_window_complete,
            segment_started_at=timestamp,
            raw_bytes=sum(len(record) for record in records),
            records=records,
            triggers=[trigger],
        )
        return True

    def finish(self) -> int:
        for check_id in list(self.active):
            self._finalize(check_id, complete_after_window=False,
                           reason="collection_stopped", ended_at=self.last_observed_at)
        return self.completed

    def _finalize(
        self, check_id: str, *, complete_after_window: bool,
        reason: str, ended_at: datetime | None,
    ) -> str:
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
            "capture_end_reason": reason,
            "capture_end_timestamp": (ended_at or session.first_trigger_at).strftime(_RAW_TS_FORMAT)[:-3],
            "segment_started_at": session.segment_started_at.strftime(_RAW_TS_FORMAT)[:-3],
            "continuation_of": session.continuation_of,
            "capture_limits": {
                "max_seconds": MAX_CONTEXT_SECONDS,
                "max_bytes": MAX_CONTEXT_BYTES,
                "max_records": MAX_CONTEXT_RECORDS,
                "max_triggers": MAX_CONTEXT_TRIGGERS,
            },
        }
        temp_path = json_path.with_name(json_path.name + ".tmp")
        temp_path.write_text(
            json.dumps(metadata, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(json_path)
        self.completed += 1
        return raw_path.name
