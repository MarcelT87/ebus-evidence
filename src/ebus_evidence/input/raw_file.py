from __future__ import annotations

import re
from pathlib import Path
from typing import Iterator

from ebus_evidence.models import Frame


_TIMESTAMP = rb"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3}"
_RECORD_START_RE = re.compile(rb"(?=" + _TIMESTAMP + rb" [<>])")
_RECORD_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d{3})\s+(.+)$",
    re.S,
)
_SEGMENT_RE = re.compile(r"([<>])([0-9a-fA-F]+)")

MAX_RAW_RECORD_BYTES = 1024 * 1024
RAW_READ_CHUNK_BYTES = 64 * 1024
_RECORD_BOUNDARY_OVERLAP_BYTES = 64
_OVERSIZE_RECORD_MARKER = b"__EBUS_EVIDENCE_OVERSIZED_RAW_RECORD__"


class RawParseError(ValueError):
    pass


class RawNonFrame(RawParseError):
    """A valid ebusd message-mode raw record that is not a complete eBUS frame."""

    def __init__(self, kind: str, detail: str):
        super().__init__(detail)
        self.kind = kind


def unescape_wire(data: bytes) -> bytes:
    """Undo eBUS A9 byte stuffing."""
    out = bytearray()
    i = 0
    while i < len(data):
        byte = data[i]
        if byte != 0xA9:
            out.append(byte)
            i += 1
            continue
        if i + 1 >= len(data):
            raise RawParseError("truncated eBUS escape")
        escaped = data[i + 1]
        if escaped == 0x00:
            out.append(0xA9)
        elif escaped == 0x01:
            out.append(0xAA)
        else:
            raise RawParseError(f"invalid eBUS escape A9 {escaped:02x}")
        i += 2
    return bytes(out)


def resolve_raw_sources(path: str | Path, include_rotated: bool = False) -> list[Path]:
    """Return raw sources in chronological order.

    ebusd rotates FILE to FILE.old. When requested, the rotated file is read
    first and the active file second.
    """
    active = Path(path)
    sources: list[Path] = []
    if include_rotated:
        rotated = Path(str(active) + ".old")
        if rotated.is_file():
            sources.append(rotated)
    sources.append(active)
    return sources


class RawRecordSplitter:
    """Incrementally split raw records with bounded pending memory.

    Normal eBUS message-mode records are tiny. A corrupt input that never
    provides the next timestamp delimiter must not make the pending buffer grow
    without bound. Records exceeding the configured safety limit are represented
    by one small internal marker and skipped by the normal parser.
    """

    def __init__(self, *, max_record_bytes: int = MAX_RAW_RECORD_BYTES):
        if max_record_bytes <= 0:
            raise ValueError("max_record_bytes must be greater than zero")
        self.max_record_bytes = max_record_bytes
        self._buffer = b""
        self._discarding_oversize = False

    @property
    def pending(self) -> bytes:
        return self._buffer

    @property
    def pending_bytes(self) -> int:
        return len(self._buffer)

    @property
    def discarding_oversize(self) -> bool:
        return self._discarding_oversize

    def reset(self) -> None:
        self._buffer = b""
        self._discarding_oversize = False

    def _retain_boundary_overlap(self) -> None:
        if len(self._buffer) > _RECORD_BOUNDARY_OVERLAP_BYTES:
            self._buffer = self._buffer[-_RECORD_BOUNDARY_OVERLAP_BYTES:]

    def feed(self, data: bytes, *, flush: bool = False) -> list[bytes]:
        if data:
            self._buffer += data

        records: list[bytes] = []

        while True:
            starts = [
                match.start()
                for match in _RECORD_START_RE.finditer(self._buffer)
            ]

            if self._discarding_oversize:
                if starts:
                    self._buffer = self._buffer[starts[0] :]
                    self._discarding_oversize = False
                    continue
                if flush:
                    self.reset()
                else:
                    self._retain_boundary_overlap()
                break

            if not starts:
                if flush:
                    self._buffer = b""
                else:
                    self._retain_boundary_overlap()
                break

            if starts[0] > 0:
                self._buffer = self._buffer[starts[0] :]
                continue

            if len(starts) >= 2:
                end = starts[1]
                if end > self.max_record_bytes:
                    records.append(_OVERSIZE_RECORD_MARKER)
                else:
                    record = self._buffer[:end].strip()
                    if record:
                        records.append(record)
                self._buffer = self._buffer[end:]
                continue

            if len(self._buffer) > self.max_record_bytes:
                records.append(_OVERSIZE_RECORD_MARKER)
                self._discarding_oversize = True
                self._retain_boundary_overlap()
                break

            if flush:
                record = self._buffer.strip()
                if record:
                    records.append(record)
                self._buffer = b""
            break

        return records


def split_record_buffer(buffer: bytes, *, flush: bool = False) -> tuple[list[bytes], bytes]:
    """Split timestamp-delimited raw data while preserving a possible tail record."""
    starts = [match.start() for match in _RECORD_START_RE.finditer(buffer)]
    if not starts:
        return ([], b"") if flush else ([], buffer)

    if starts[0] > 0:
        buffer = buffer[starts[0] :]
        starts = [match.start() for match in _RECORD_START_RE.finditer(buffer)]

    records: list[bytes] = []
    for index in range(len(starts) - 1):
        record = buffer[starts[index] : starts[index + 1]].strip()
        if record:
            records.append(record)

    tail = buffer[starts[-1] :]
    if flush:
        record = tail.strip()
        if record:
            records.append(record)
        tail = b""

    return records, tail


def split_records(path: str | Path, chunk_size: int = 1024 * 1024) -> Iterator[bytes]:
    """Yield timestamp-delimited records from a raw-log file with bounded memory."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    splitter = RawRecordSplitter()
    with Path(path).open("rb") as handle:
        while chunk := handle.read(chunk_size):
            yield from splitter.feed(chunk)

    yield from splitter.feed(b"", flush=True)


def parse_record(record: bytes | str) -> Frame:
    """Parse one ebusd message-mode raw record into a normalized frame."""
    if isinstance(record, bytes) and record == _OVERSIZE_RECORD_MARKER:
        raise RawParseError(
            f"raw record exceeds {MAX_RAW_RECORD_BYTES} byte safety limit"
        )
    if isinstance(record, bytes):
        try:
            line = record.decode("ascii", "strict").strip()
        except UnicodeDecodeError as exc:
            raise RawParseError("record is not ASCII") from exc
    else:
        line = record.strip()

    match = _RECORD_RE.match(line)
    if not match:
        raise RawParseError("record has no supported timestamp prefix")
    timestamp, body = match.groups()

    segments = _SEGMENT_RE.findall(body)
    if not segments:
        raise RawParseError("record contains no eBUS hex segment")

    first_direction, first_hex = segments[0]
    if len(first_hex) % 2:
        raise RawParseError("master segment has an odd number of hex digits")

    try:
        master = unescape_wire(bytes.fromhex(first_hex))
    except ValueError as exc:
        raise RawParseError(str(exc)) from exc

    if len(master) < 6:
        raise RawNonFrame(
            "short_fragment",
            f"short bus fragment ({master.hex() or 'empty'})",
        )

    request_length = master[4]
    request_end = 5 + request_length
    if request_end > len(master):
        raise RawNonFrame(
            "truncated_request",
            "declared request length exceeds available telegram bytes",
        )

    source = f"{master[0]:02x}"
    target = f"{master[1]:02x}"
    pbsb = f"{master[2]:02x}{master[3]:02x}"
    request = master[4:request_end].hex()
    response = None

    try:
        if first_direction == "<":
            pos = request_end + 1
            if pos < len(master) and master[pos] in (0x00, 0xFF):
                pos += 1
            if pos < len(master):
                response_length = master[pos]
                if response_length <= 32 and pos + 1 + response_length <= len(master):
                    response = master[pos : pos + 1 + response_length].hex()
        else:
            incoming = next((value for direction, value in segments[1:] if direction == "<"), None)
            if incoming and len(incoming) % 2 == 0:
                slave = unescape_wire(bytes.fromhex(incoming))
                pos = 1 if slave and slave[0] in (0x00, 0xFF) else 0
                if pos < len(slave):
                    response_length = slave[pos]
                    if response_length <= 32 and pos + 1 + response_length <= len(slave):
                        response = slave[pos : pos + 1 + response_length].hex()
    except (RawParseError, ValueError):
        response = None

    return Frame(
        timestamp=timestamp,
        direction=first_direction,
        initiated_by_ebusd=first_direction == ">",
        source=source,
        target=target,
        pbsb=pbsb,
        request=request,
        response=response,
    )


def iter_frames(path: str | Path) -> Iterator[Frame]:
    for record in split_records(path):
        try:
            yield parse_record(record)
        except RawParseError:
            continue


def iter_frames_many(paths: list[str | Path]) -> Iterator[Frame]:
    for path in paths:
        yield from iter_frames(path)
