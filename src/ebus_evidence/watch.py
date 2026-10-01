from __future__ import annotations

import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from ebus_evidence.decoders import DecodeError, decode_value
from ebus_evidence.input.raw_file import RawParseError, parse_record, split_record_buffer
from ebus_evidence.matching import frame_matches
from ebus_evidence.models import Frame
from ebus_evidence.timeutil import normalize_timestamp


@dataclass(slots=True)
class WatchStats:
    frames: int = 0
    matches: int = 0
    skipped_records: int = 0
    partial_tail: int = 0
    rotations: int = 0
    skip_reasons: Counter[str] = field(default_factory=Counter)


class RawLogFollower:
    """Incrementally follow one ebusd raw log and survive rename/create rotation."""

    def __init__(self, path: str | Path, *, from_start: bool = False):
        self.path = Path(path)
        self.from_start = from_start
        self._handle: BinaryIO | None = None
        self._inode: tuple[int, int] | None = None
        self._buffer = b""
        self.rotations = 0

    def _open(self, *, from_start: bool) -> None:
        handle = self.path.open("rb")
        stat = os.fstat(handle.fileno())
        self._handle = handle
        self._inode = (stat.st_dev, stat.st_ino)
        if not from_start:
            handle.seek(0, os.SEEK_END)

    def start(self) -> None:
        self._open(from_start=self.from_start)

    def _consume_bytes(self, data: bytes, *, flush: bool = False) -> list[bytes]:
        records, self._buffer = split_record_buffer(self._buffer + data, flush=flush)
        return records

    def _read_available(self) -> bytes:
        if self._handle is None:
            return b""
        return self._handle.read()

    def poll(self) -> list[bytes]:
        if self._handle is None:
            self.start()

        assert self._handle is not None
        records = self._consume_bytes(self._read_available())

        try:
            path_stat = self.path.stat()
        except FileNotFoundError:
            return records

        current_inode = (path_stat.st_dev, path_stat.st_ino)
        if current_inode != self._inode:
            # The renamed file is no longer being written by ebusd, so its tail
            # is safe to flush before the new active file is opened.
            records.extend(self._consume_bytes(self._read_available(), flush=True))
            self._handle.close()
            self._handle = None
            self._inode = None
            self.rotations += 1
            self._open(from_start=True)
            records.extend(self._consume_bytes(self._read_available()))
            return records

        # Also handle copy/truncate-style rotation defensively.
        if path_stat.st_size < self._handle.tell():
            records.extend(self._consume_bytes(b"", flush=True))
            self._handle.seek(0)
            self.rotations += 1
            records.extend(self._consume_bytes(self._read_available()))

        return records

    def finish(self) -> tuple[list[bytes], bytes | None]:
        """Close the active file without assuming its final tail is complete."""
        if self._handle is None:
            return [], None

        records = self._consume_bytes(self._read_available())
        tail = self._buffer.strip() or None
        self._buffer = b""
        self._handle.close()
        self._handle = None
        return records, tail


def frame_events(
    frame: Frame,
    profile: dict[str, Any],
    *,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for check in profile["checks"]:
        if not frame_matches(frame, check["match"]):
            continue

        event: dict[str, Any] = {
            "format": "ebus-evidence-watch-event-v1",
            "check_id": check["id"],
            "description": check.get("description", check["id"]),
            "timestamp": normalize_timestamp(
                frame.timestamp,
                source_timezone=source_timezone,
                display_timezone=display_timezone,
            ),
            "source": frame.source,
            "target": frame.target,
            "pbsb": frame.pbsb,
            "request": frame.request,
            "response": frame.response,
            "initiated_by_ebusd": frame.initiated_by_ebusd,
            "value_status": "not_configured",
            "value": None,
        }

        value_spec = check.get("value")
        if value_spec is not None:
            if str(value_spec.get("from", "response")) == "response" and frame.response is None:
                event["value_status"] = "no_response"
            else:
                try:
                    event["value"] = decode_value(frame, value_spec)
                    event["value_status"] = "decoded"
                except DecodeError as exc:
                    event["value_status"] = "decode_error"
                    event["decode_error"] = str(exc)

        events.append(event)
    return events


def format_event(event: dict[str, Any]) -> str:
    timestamp = event["timestamp"].get("display") or event["timestamp"]["raw"]
    response = event["response"] or "<none>"
    suffix = ""
    if event["value_status"] == "decoded":
        suffix = f" value={event['value']}"
    elif event["value_status"] == "no_response":
        suffix = " value=<no-response>"
    elif event["value_status"] == "decode_error":
        suffix = f" value=<decode-error:{event.get('decode_error', 'unknown')}>"

    return (
        f"{timestamp} [{event['check_id']}] "
        f"{event['source']}->{event['target']} {event['pbsb']} "
        f"req={event['request']} resp={response}{suffix}"
    )


def run_watch(
    raw_path: str | Path,
    profile: dict[str, Any],
    *,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
    seconds: float | None = None,
    poll_interval: float = 0.25,
    json_lines: bool = False,
) -> WatchStats:
    follower = RawLogFollower(raw_path)
    follower.start()
    stats = WatchStats()
    started = time.monotonic()

    def consume(records: list[bytes]) -> None:
        for record in records:
            try:
                frame = parse_record(record)
            except RawParseError as exc:
                stats.skipped_records += 1
                stats.skip_reasons[str(exc)] += 1
                continue
            stats.frames += 1
            for event in frame_events(
                frame,
                profile,
                source_timezone=source_timezone,
                display_timezone=display_timezone,
            ):
                stats.matches += 1
                if json_lines:
                    print(json.dumps(event, sort_keys=True), flush=True)
                else:
                    print(format_event(event), flush=True)

    try:
        while seconds is None or time.monotonic() - started < seconds:
            consume(follower.poll())
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        pass
    finally:
        records, tail = follower.finish()
        consume(records)
        if tail is not None:
            try:
                frame = parse_record(tail)
            except RawParseError:
                # The active raw log can be stopped between two writes. Do not
                # label that unfinished final record as a parser failure.
                stats.partial_tail += 1
            else:
                stats.frames += 1
                for event in frame_events(
                    frame,
                    profile,
                    source_timezone=source_timezone,
                    display_timezone=display_timezone,
                ):
                    stats.matches += 1
                    if json_lines:
                        print(json.dumps(event, sort_keys=True), flush=True)
                    else:
                        print(format_event(event), flush=True)
        stats.rotations = follower.rotations

    return stats
