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

_ACK = 0x00
_NAK = 0xFF
_MASTER_ADDRESS_NIBBLES = frozenset((0x0, 0x1, 0x3, 0x7, 0xF))


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


def _crc_update(crc: int, value: int) -> int:
    """Update eBUS CRC-8 for one on-wire byte."""
    for _ in range(8):
        if crc & 0x80:
            crc = ((crc << 1) ^ 0x9B) & 0xFF
        else:
            crc = (crc << 1) & 0xFF
    return crc ^ value


def calculate_ebus_crc(data: bytes) -> int:
    """Calculate eBUS CRC-8 using the same byte-stuffing rules as ebusd.

    The input contains logical/unescaped symbols. eBUS byte stuffing is part of
    the CRC calculation, so logical A9/AA symbols are expanded to A9 00/A9 01
    before updating the checksum.
    """
    crc = 0
    for value in data:
        if value == 0xA9:
            crc = _crc_update(crc, 0xA9)
            crc = _crc_update(crc, 0x00)
        elif value == 0xAA:
            crc = _crc_update(crc, 0xA9)
            crc = _crc_update(crc, 0x01)
        else:
            crc = _crc_update(crc, value)
    return crc


def _validate_crc(payload: bytes, observed: int, *, kind: str, label: str) -> None:
    expected = calculate_ebus_crc(payload)
    if observed != expected:
        raise RawNonFrame(
            kind,
            f"{label} CRC mismatch: expected {expected:02x}, observed {observed:02x}",
        )


def _parse_response(data: bytes, pos: int) -> tuple[str | None, int]:
    """Parse and CRC-check one optional response at pos.

    Return the normalized response and the first unconsumed transaction byte.
    """
    if pos >= len(data):
        return None, pos

    response_length = data[pos]
    if response_length > 32:
        raise RawNonFrame(
            "invalid_response_length",
            f"response length {response_length} exceeds supported eBUS payload size",
        )

    response_end = pos + 1 + response_length
    if response_end > len(data):
        raise RawNonFrame(
            "truncated_response",
            "declared response length exceeds available telegram bytes",
        )
    if response_end == len(data):
        raise RawNonFrame(
            "missing_response_crc",
            "response payload is present but response CRC is missing",
        )

    response = data[pos:response_end]
    _validate_crc(
        response,
        data[response_end],
        kind="invalid_response_crc",
        label="response",
    )
    return response.hex(), response_end + 1


def _is_master_address(address: int) -> bool:
    """Match ebusd's eBUS master-address classification."""
    return (
        (address & 0x0F) in _MASTER_ADDRESS_NIBBLES
        and ((address & 0xF0) >> 4) in _MASTER_ADDRESS_NIBBLES
    )


def _consume_command_ack(data: bytes, pos: int) -> int:
    """Consume one positive command acknowledgement or fail closed."""
    if pos >= len(data):
        raise RawNonFrame(
            "missing_command_ack",
            "transaction is missing the command acknowledgement",
        )

    value = data[pos]
    if value == _NAK:
        raise RawNonFrame(
            "negative_command_ack",
            "command was negatively acknowledged (NAK); retry transaction is not evidence",
        )
    if value != _ACK:
        raise RawNonFrame(
            "invalid_command_ack",
            f"expected command ACK 00, observed {value:02x}",
        )
    return pos + 1


def _consume_response_ack(data: bytes, pos: int) -> int:
    """Consume one positive response acknowledgement or fail closed."""
    if pos >= len(data):
        raise RawNonFrame(
            "missing_response_ack",
            "transaction is missing the final response acknowledgement",
        )

    value = data[pos]
    if value == _NAK:
        raise RawNonFrame(
            "negative_response_ack",
            "response was negatively acknowledged (NAK); retry transaction is not evidence",
        )
    if value != _ACK:
        raise RawNonFrame(
            "invalid_response_ack",
            f"expected response ACK 00, observed {value:02x}",
        )
    return pos + 1


def _parse_passive_transaction(
    data: bytes,
    pos: int,
    *,
    expects_response: bool,
) -> str | None:
    """Validate the post-command bytes of one passive message-mode transaction."""
    pos = _consume_command_ack(data, pos)
    if pos >= len(data):
        if expects_response:
            raise RawNonFrame(
                "missing_response",
                "slave transaction ended after command ACK without a response",
            )
        return None
    if not expects_response:
        raise RawNonFrame(
            "unexpected_transaction_tail",
            "master-target transaction contains bytes after the command acknowledgement",
        )

    response, pos = _parse_response(data, pos)
    pos = _consume_response_ack(data, pos)
    if pos != len(data):
        raise RawNonFrame(
            "unexpected_transaction_tail",
            "unexpected bytes remain after the final response acknowledgement",
        )
    return response


def _decode_direction_segment(value: str, label: str) -> bytes:
    if len(value) % 2:
        raise RawParseError(f"{label} segment has an odd number of hex digits")
    try:
        return unescape_wire(bytes.fromhex(value))
    except ValueError as exc:
        raise RawParseError(str(exc)) from exc


def _parse_ebusd_transaction(
    segments: list[tuple[str, str]],
    *,
    expects_response: bool,
) -> str | None:
    """Validate direction changes for a transaction initiated by ebusd."""
    if len(segments) == 1:
        raise RawNonFrame(
            "missing_command_ack",
            "ebusd-initiated transaction is missing the command acknowledgement",
        )

    direction, incoming_hex = segments[1]
    if direction != "<":
        raise RawNonFrame(
            "unexpected_transaction_direction",
            "expected incoming command acknowledgement after ebusd request",
        )

    incoming = _decode_direction_segment(incoming_hex, "response")
    pos = _consume_command_ack(incoming, 0)

    if pos >= len(incoming):
        if len(segments) != 2:
            raise RawNonFrame(
                "unexpected_transaction_tail",
                "unexpected direction segment after command-only acknowledgement",
            )
        if expects_response:
            raise RawNonFrame(
                "missing_response",
                "slave transaction ended after command ACK without a response",
            )
        return None
    if not expects_response:
        raise RawNonFrame(
            "unexpected_transaction_tail",
            "master-target transaction contains a response after the command acknowledgement",
        )

    response, pos = _parse_response(incoming, pos)
    if pos != len(incoming):
        raise RawNonFrame(
            "unexpected_transaction_tail",
            "unexpected bytes remain in the incoming response segment",
        )

    if len(segments) < 3:
        raise RawNonFrame(
            "missing_response_ack",
            "ebusd-initiated response is missing the final outgoing acknowledgement",
        )

    ack_direction, ack_hex = segments[2]
    if ack_direction != ">":
        raise RawNonFrame(
            "unexpected_transaction_direction",
            "expected outgoing response acknowledgement after incoming response",
        )
    ack_data = _decode_direction_segment(ack_hex, "response acknowledgement")
    ack_end = _consume_response_ack(ack_data, 0)
    if ack_end != len(ack_data) or len(segments) != 3:
        raise RawNonFrame(
            "unexpected_transaction_tail",
            "unexpected bytes or direction segments remain after the final response acknowledgement",
        )

    return response


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
                # Emit every complete record found by this scan. Emitting only
                # one per scan rescans the whole buffer per record, which made
                # splitting quadratic in the chunk size.
                for begin, end in zip(starts, starts[1:]):
                    if end - begin > self.max_record_bytes:
                        records.append(_OVERSIZE_RECORD_MARKER)
                    else:
                        record = self._buffer[begin:end].strip()
                        if record:
                            records.append(record)
                self._buffer = self._buffer[starts[-1] :]
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


def split_records(
    path: str | Path,
    chunk_size: int = 1024 * 1024,
    *,
    max_record_bytes: int = MAX_RAW_RECORD_BYTES,
) -> Iterator[bytes]:
    """Yield timestamp-delimited records from a raw-log file with bounded memory."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than zero")

    splitter = RawRecordSplitter(max_record_bytes=max_record_bytes)
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

    if "..." in body:
        raise RawNonFrame(
            "truncated_message_record",
            "ebusd message-mode record is an explicitly truncated/continued fragment",
        )

    segment_matches = list(_SEGMENT_RE.finditer(body))
    if not segment_matches:
        raise RawParseError("record contains no eBUS hex segment")

    cursor = 0
    for segment_match in segment_matches:
        if segment_match.start() != cursor:
            raise RawParseError("record contains unsupported text between eBUS segments")
        cursor = segment_match.end()
    if cursor != len(body):
        raise RawParseError("record contains unsupported trailing text")

    segments = [segment_match.groups() for segment_match in segment_matches]
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
    if request_end == len(master):
        raise RawNonFrame(
            "missing_master_crc",
            "complete request payload is present but master CRC is missing",
        )

    _validate_crc(
        master[:request_end],
        master[request_end],
        kind="invalid_master_crc",
        label="master",
    )

    source = f"{master[0]:02x}"
    target = f"{master[1]:02x}"
    pbsb = f"{master[2]:02x}{master[3]:02x}"
    request = master[4:request_end].hex()
    response = None
    is_broadcast = master[1] == 0xFE
    expects_response = not is_broadcast and not _is_master_address(master[1])

    if first_direction == "<":
        if len(segments) != 1:
            raise RawNonFrame(
                "unexpected_transaction_tail",
                "passive transaction contains additional direction segments",
            )
        if is_broadcast:
            if request_end + 1 != len(master):
                raise RawNonFrame(
                    "unexpected_transaction_tail",
                    "broadcast transaction contains bytes after the master CRC",
                )
        else:
            response = _parse_passive_transaction(
                master,
                request_end + 1,
                expects_response=expects_response,
            )
    else:
        if request_end + 1 != len(master):
            raise RawNonFrame(
                "unexpected_transaction_tail",
                "ebusd-initiated command segment contains bytes after the master CRC",
            )
        if is_broadcast:
            if len(segments) != 1:
                raise RawNonFrame(
                    "unexpected_transaction_tail",
                    "broadcast transaction contains acknowledgement/response segments",
                )
        else:
            response = _parse_ebusd_transaction(
                segments,
                expects_response=expects_response,
            )

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
