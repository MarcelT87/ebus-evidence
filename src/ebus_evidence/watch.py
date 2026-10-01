from __future__ import annotations

import hashlib
import json
import os
import time
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, BinaryIO

from ebus_evidence.decoders import DecodeError, decode_value
from ebus_evidence.input.raw_file import (
    RawNonFrame,
    RawParseError,
    parse_record,
    split_record_buffer,
)
from ebus_evidence.matching import frame_matches
from ebus_evidence.models import Frame
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.timeutil import normalize_timestamp


class ResumeError(RuntimeError):
    pass


@dataclass(slots=True)
class WatchStats:
    frames: int = 0
    matches: int = 0
    non_frame_records: int = 0
    skipped_records: int = 0
    partial_tail: int = 0
    rotations: int = 0
    resume_mode: str = "fresh_end"
    non_frame_kinds: Counter[str] = field(default_factory=Counter)
    non_frame_samples: dict[str, list[str]] = field(default_factory=dict)
    skip_reasons: Counter[str] = field(default_factory=Counter)
    skip_samples: dict[str, list[str]] = field(default_factory=dict)


class RawLogFollower:
    """Incrementally follow one ebusd raw log and survive rename/create rotation."""

    def __init__(
        self,
        path: str | Path,
        *,
        checkpoint: dict[str, Any] | None = None,
        from_start: bool = False,
    ):
        self.path = Path(path)
        self.from_start = from_start
        self.requested_checkpoint = checkpoint
        self._handle: BinaryIO | None = None
        self._inode: tuple[int, int] | None = None
        self._buffer = b""
        self.rotations = 0
        self.resume_mode = "fresh_end"

    @staticmethod
    def _identity(stat: os.stat_result) -> tuple[int, int]:
        return stat.st_dev, stat.st_ino

    @staticmethod
    def _identity_matches(stat: os.stat_result, checkpoint: dict[str, Any]) -> bool:
        return (
            stat.st_dev == checkpoint["device"]
            and stat.st_ino == checkpoint["inode"]
        )

    @staticmethod
    def _anchor_matches(
        handle: BinaryIO,
        checkpoint: dict[str, Any],
    ) -> bool:
        anchor_sha256 = checkpoint.get("anchor_sha256")
        anchor_start = checkpoint.get("anchor_start")
        if anchor_sha256 is None or anchor_start is None:
            # Backward compatibility for state files written before content
            # anchors were introduced. The next saved checkpoint will be
            # upgraded automatically.
            return True

        offset = checkpoint["offset"]
        current = handle.tell()
        try:
            handle.seek(anchor_start)
            data = handle.read(offset - anchor_start)
        finally:
            handle.seek(current)
        return hashlib.sha256(data).hexdigest() == anchor_sha256

    def _try_open_checkpoint(
        self,
        path: Path,
        checkpoint: dict[str, Any],
    ) -> bool:
        try:
            handle = path.open("rb")
        except FileNotFoundError:
            return False

        stat = os.fstat(handle.fileno())
        if not self._identity_matches(stat, checkpoint):
            handle.close()
            return False
        if checkpoint["offset"] > stat.st_size:
            handle.close()
            return False
        if not self._anchor_matches(handle, checkpoint):
            handle.close()
            return False

        handle.seek(checkpoint["offset"])
        self._handle = handle
        self._inode = self._identity(stat)
        return True

    def _open_path(self, path: Path, *, offset: int | None = None, from_start: bool = False) -> None:
        handle = path.open("rb")
        stat = os.fstat(handle.fileno())
        self._handle = handle
        self._inode = self._identity(stat)

        if offset is not None:
            if offset > stat.st_size:
                handle.close()
                self._handle = None
                self._inode = None
                raise ResumeError(
                    f"checkpoint offset {offset} is beyond file size {stat.st_size}"
                )
            handle.seek(offset)
        elif not from_start:
            handle.seek(0, os.SEEK_END)

    def start(self) -> None:
        checkpoint = self.requested_checkpoint
        if checkpoint is None:
            self._open_path(self.path, from_start=self.from_start)
            self.resume_mode = "from_start" if self.from_start else "fresh_end"
            return

        if self._try_open_checkpoint(self.path, checkpoint):
            self.resume_mode = "active"
            return

        rotated = Path(str(self.path) + ".old")
        if self._try_open_checkpoint(rotated, checkpoint):
            self.resume_mode = "rotated"
            return

        raise ResumeError(
            "saved checkpoint no longer matches the active raw log or its .old rotation"
        )

    def _consume_bytes(self, data: bytes, *, flush: bool = False) -> list[bytes]:
        records, self._buffer = split_record_buffer(self._buffer + data, flush=flush)
        return records

    def _read_available(self) -> bytes:
        if self._handle is None:
            return b""
        return self._handle.read()

    def checkpoint(self, *, end: bool = False) -> dict[str, Any]:
        if self._handle is None or self._inode is None:
            raise ResumeError("raw follower is not open")

        current = self._handle.tell()
        offset = current
        if not end:
            offset -= len(self._buffer)

        anchor_start = max(0, offset - 256)
        try:
            self._handle.seek(anchor_start)
            anchor = self._handle.read(offset - anchor_start)
        finally:
            self._handle.seek(current)

        return {
            "device": self._inode[0],
            "inode": self._inode[1],
            "offset": offset,
            "anchor_start": anchor_start,
            "anchor_sha256": hashlib.sha256(anchor).hexdigest(),
        }

    def poll(self) -> list[bytes]:
        if self._handle is None:
            self.start()

        assert self._handle is not None
        records = self._consume_bytes(self._read_available())

        try:
            path_stat = self.path.stat()
        except FileNotFoundError:
            return records

        current_inode = self._identity(path_stat)
        if current_inode != self._inode:
            # The current handle refers to the renamed old file. Drain it fully,
            # then switch to the new active file at byte zero.
            records.extend(self._consume_bytes(self._read_available(), flush=True))
            self._handle.close()
            self._handle = None
            self._inode = None
            self.rotations += 1
            self._open_path(self.path, from_start=True)
            records.extend(self._consume_bytes(self._read_available()))
            return records

        # Also handle copy/truncate-style rotation defensively.
        if path_stat.st_size < self._handle.tell():
            records.extend(self._consume_bytes(b"", flush=True))
            self._handle.seek(0)
            self.rotations += 1
            records.extend(self._consume_bytes(self._read_available()))

        return records

    def finish(
        self,
    ) -> tuple[
        list[bytes],
        bytes | None,
        bool,
        dict[str, Any],
        dict[str, Any],
    ]:
        """Close the file and return safe/end checkpoints around the final tail."""
        if self._handle is None:
            raise ResumeError("raw follower is not open")

        records = self._consume_bytes(self._read_available())
        tail_bytes = self._buffer
        tail_terminated = tail_bytes.endswith(b"\n")
        tail = tail_bytes.strip() or None
        safe_checkpoint = self.checkpoint()
        end_checkpoint = self.checkpoint(end=True)

        self._buffer = b""
        self._handle.close()
        self._handle = None
        return records, tail, tail_terminated, safe_checkpoint, end_checkpoint


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


def _bounded_sample(record: bytes) -> str:
    text = record.decode("ascii", "replace").strip().replace("\n", "\\n")
    if len(text) > 160:
        text = text[:157] + "..."
    return f"bytes={len(record)} record={text}"


def run_watch(
    raw_path: str | Path,
    profile: dict[str, Any],
    *,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
    seconds: float | None = None,
    poll_interval: float = 0.25,
    json_lines: bool = False,
    state_store: EvidenceStateStore | None = None,
) -> WatchStats:
    follower = RawLogFollower(
        raw_path,
        checkpoint=state_store.checkpoint if state_store is not None else None,
    )
    follower.start()

    stats = WatchStats(resume_mode=follower.resume_mode)
    started = time.monotonic()

    if state_store is not None and state_store.checkpoint is None:
        state_store.set_checkpoint(follower.checkpoint())

    def add_event(event: dict[str, Any]) -> None:
        stats.matches += 1
        if state_store is not None:
            # Persist events and the file cursor in one atomic state write after
            # the current raw batch has been consumed.
            state_store.add(event, save=False)
        if json_lines:
            print(json.dumps(event, sort_keys=True), flush=True)
        else:
            print(format_event(event), flush=True)

    def classify_non_frame(record: bytes, exc: RawNonFrame) -> None:
        stats.non_frame_records += 1
        stats.non_frame_kinds[exc.kind] += 1
        samples = stats.non_frame_samples.setdefault(exc.kind, [])
        if len(samples) < 3:
            samples.append(_bounded_sample(record))

    def classify_skip(record: bytes, exc: RawParseError) -> None:
        reason = str(exc)
        stats.skipped_records += 1
        stats.skip_reasons[reason] += 1
        samples = stats.skip_samples.setdefault(reason, [])
        if len(samples) < 3:
            samples.append(_bounded_sample(record))

    def consume(records: list[bytes]) -> None:
        for record in records:
            try:
                frame = parse_record(record)
            except RawNonFrame as exc:
                classify_non_frame(record, exc)
                continue
            except RawParseError as exc:
                classify_skip(record, exc)
                continue

            stats.frames += 1
            for event in frame_events(
                frame,
                profile,
                source_timezone=source_timezone,
                display_timezone=display_timezone,
            ):
                add_event(event)

    try:
        while seconds is None or time.monotonic() - started < seconds:
            records = follower.poll()
            consume(records)
            if state_store is not None:
                state_store.set_checkpoint(follower.checkpoint())
            time.sleep(poll_interval)
    except KeyboardInterrupt:
        pass
    finally:
        (
            records,
            tail,
            tail_terminated,
            safe_checkpoint,
            end_checkpoint,
        ) = follower.finish()
        consume(records)

        final_checkpoint = safe_checkpoint
        if tail is not None:
            if not tail_terminated:
                stats.partial_tail += 1
            else:
                try:
                    frame = parse_record(tail)
                except RawNonFrame as exc:
                    classify_non_frame(tail, exc)
                    final_checkpoint = end_checkpoint
                except RawParseError as exc:
                    classify_skip(tail, exc)
                    final_checkpoint = end_checkpoint
                else:
                    stats.frames += 1
                    for event in frame_events(
                        frame,
                        profile,
                        source_timezone=source_timezone,
                        display_timezone=display_timezone,
                    ):
                        add_event(event)
                    final_checkpoint = end_checkpoint
        else:
            final_checkpoint = end_checkpoint

        if state_store is not None:
            state_store.set_checkpoint(final_checkpoint)
        stats.rotations = follower.rotations

    return stats
