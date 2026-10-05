from pathlib import Path

import pytest

from ebus_evidence.input.raw_file import (
    RawNonFrame,
    RawParseError,
    RawRecordSplitter,
    calculate_ebus_crc,
    parse_record,
    resolve_raw_sources,
    split_records,
    unescape_wire,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sample.raw"


def test_unescape_wire_handles_a9_and_aa():
    assert unescape_wire(bytes.fromhex("01a90002a90103")) == bytes.fromhex("01a902aa03")


def test_parser_keeps_request_length_byte():
    frame = parse_record(b"2026-09-23 10:00:00.000 <1008b5070209004f00")
    assert frame.source == "10"
    assert frame.target == "08"
    assert frame.pbsb == "b507"
    assert frame.request == "020900"
    assert frame.initiated_by_ebusd is False


def test_parser_extracts_passive_response():
    frame = parse_record(
        b"2026-10-01 10:00:00.000 <f108b50905540200a80ead00080201a80e0000b0407500"
    )
    assert frame.request == "05540200a80e"
    assert frame.response == "080201a80e0000b040"



def test_ebus_crc_matches_upstream_escaped_symbol_vector():
    # john30/ebusd expects CRC 0x77 for these logical symbols, including
    # A9 and AA byte-stuffing cases.
    assert calculate_ebus_crc(bytes.fromhex("10feb5050427a915aa")) == 0x77


def test_parser_rejects_missing_master_crc():
    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(b"2026-09-23 10:00:00.000 <1008b507020900")
    assert excinfo.value.kind == "missing_master_crc"


@pytest.mark.parametrize(
    ("record", "expected", "observed"),
    [
        (
            b"2026-09-05 00:28:23.183 <0376b5120613001000000200bc0210ff0d00",
            "d6",
            "00",
        ),
        (
            b"2026-06-24 05:52:47.711 <0376b5120613000c000009ff0000ff5e00",
            "d9",
            "ff",
        ),
    ],
)
def test_parser_rejects_real_issue22_crc_invalid_b512_records(
    record, expected, observed
):
    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(record)
    assert excinfo.value.kind == "invalid_master_crc"
    assert f"expected {expected}, observed {observed}" in str(excinfo.value)


def test_parser_rejects_invalid_response_crc():
    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(
            b"2026-10-01 10:00:00.000 "
            b"<0376b5120613000c000006d6000200ff0000"
        )
    assert excinfo.value.kind == "invalid_response_crc"
    assert "expected d3, observed 00" in str(excinfo.value)


def test_parser_crc_checks_ebusd_initiated_response():
    frame = parse_record(
        b"2026-10-01 10:00:00.000 "
        b">f108b50905540200ba0834<00080201ba0820000000e7>00"
    )
    assert frame.initiated_by_ebusd is True
    assert frame.request == "05540200ba08"
    assert frame.response == "080201ba0820000000"



def test_parser_accepts_complete_broadcast_without_ack():
    frame = parse_record(
        b"2026-10-01 10:00:00.000 <10feb5050427a90015a90177"
    )
    assert frame.target == "fe"
    assert frame.request == "0427a915aa"
    assert frame.response is None


@pytest.mark.parametrize(
    ("record", "kind"),
    [
        (
            b"2026-10-01 10:00:00.000 <1008b5070209004f",
            "missing_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 <10feb5050427a90015a9017700",
            "unexpected_transaction_tail",
        ),
        (
            b"2026-10-01 10:00:00.000 <1008b5070209004fff",
            "negative_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b"<1008b5070209004fff1008b5070209004f00",
            "negative_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b"<f108b50905540200a80ead00080201a80e0000b04075ff",
            "negative_response_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b"<f108b50905540200a80ead00080201a80e0000b04075",
            "missing_response_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b"<f108b50905540200a80ead00080201a80e0000b040750001",
            "unexpected_transaction_tail",
        ),
    ],
)
def test_parser_rejects_passive_nak_retry_and_invalid_transaction_tails(
    record, kind
):
    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(record)
    assert excinfo.value.kind == kind


@pytest.mark.parametrize(
    ("record", "kind"),
    [
        (
            b"2026-10-01 10:00:00.000 >f108b50905540200ba0834",
            "missing_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 >f108b50905540200ba0834>00",
            "unexpected_transaction_direction",
        ),
        (
            b"2026-10-01 10:00:00.000 >f108b50905540200ba0834<ff",
            "negative_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b">f108b50905540200ba0834<ff"
            b">f108b50905540200ba0834<00080201ba0820000000e7>00",
            "negative_command_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b">f108b50905540200ba0834<00080201ba0820000000e7>ff",
            "negative_response_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b">f108b50905540200ba0834<00080201ba0820000000e7",
            "missing_response_ack",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b">f108b50905540200ba0834<00080201ba0820000000e7>0001",
            "unexpected_transaction_tail",
        ),
        (
            b"2026-10-01 10:00:00.000 "
            b">f108b50905540200ba083400<00080201ba0820000000e7>00",
            "unexpected_transaction_tail",
        ),
    ],
)
def test_parser_rejects_ebusd_nak_retry_and_invalid_transaction_tails(
    record, kind
):
    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(record)
    assert excinfo.value.kind == kind


def test_split_records_reads_complete_closed_file():
    records = list(split_records(FIXTURE, chunk_size=17))
    assert len(records) == 5


def test_rotated_source_is_ordered_before_active(tmp_path):
    active = tmp_path / "ebusd.raw"
    rotated = tmp_path / "ebusd.raw.old"
    active.write_text("active", encoding="ascii")
    rotated.write_text("old", encoding="ascii")

    assert resolve_raw_sources(active, include_rotated=True) == [rotated, active]
    assert resolve_raw_sources(active, include_rotated=False) == [active]


def test_split_record_buffer_keeps_tail_until_next_record():
    from ebus_evidence.input.raw_file import split_record_buffer

    first = b"2026-10-01 10:00:00.000 <1008b5070209004f00"
    second = b"2026-10-01 10:00:01.000 <1008b5070209004f00"
    records, tail = split_record_buffer(first + b"\n" + second)

    assert records == [first]
    assert tail == second

    final, tail = split_record_buffer(tail, flush=True)
    assert final == [second]
    assert tail == b""


def test_short_message_mode_record_is_non_frame():
    import pytest

    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(b"2026-10-01 21:08:32.675 <00")
    assert excinfo.value.kind == "short_fragment"
    assert "00" in str(excinfo.value)

    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(b"2026-10-01 21:09:20.589 <01")
    assert excinfo.value.kind == "short_fragment"


def test_truncated_declared_request_is_non_frame():
    import pytest

    with pytest.raises(RawNonFrame) as excinfo:
        parse_record(b"2026-09-25 13:15:04.714 >3115b55503a400")
    assert excinfo.value.kind == "truncated_request"
    assert "declared request length" in str(excinfo.value)


def test_incremental_splitter_bounds_unframed_garbage():
    splitter = RawRecordSplitter(max_record_bytes=128)

    assert splitter.feed(b"x" * 10000) == []
    assert splitter.pending_bytes <= 64


def test_incremental_splitter_skips_oversized_record_and_recovers():
    import pytest

    splitter = RawRecordSplitter(max_record_bytes=128)
    oversized = (
        b"2026-10-01 10:00:00.000 <"
        + b"aa" * 100
    )
    valid = b"2026-10-01 10:00:01.000 <1008b5070209004f00"

    first = splitter.feed(oversized)
    assert len(first) == 1
    with pytest.raises(RawParseError, match="safety limit"):
        parse_record(first[0])

    recovered = splitter.feed(b"\n" + valid, flush=True)
    assert len(recovered) == 1
    assert parse_record(recovered[0]).request == "020900"


def test_split_records_skips_oversized_record_without_large_pending_buffer(tmp_path):
    import pytest

    path = tmp_path / "oversized.raw"
    oversized = (
        b"2026-10-01 10:00:00.000 <"
        + b"aa" * 100
        + b"\n"
    )
    valid = b"2026-10-01 10:00:01.000 <1008b5070209004f00\n"
    path.write_bytes(oversized + valid)

    records = list(
        split_records(
            path,
            chunk_size=31,
            max_record_bytes=128,
        )
    )

    assert len(records) == 2
    with pytest.raises(RawParseError, match="safety limit"):
        parse_record(records[0])
    assert parse_record(records[1]).request == "020900"


def test_incremental_splitter_scans_buffer_a_bounded_number_of_times(monkeypatch):
    import ebus_evidence.input.raw_file as raw_file

    pattern = raw_file._RECORD_START_RE
    scans = 0

    class CountingPattern:
        def finditer(self, buffer):
            nonlocal scans
            scans += 1
            return pattern.finditer(buffer)

    monkeypatch.setattr(raw_file, "_RECORD_START_RE", CountingPattern())
    data = b"".join(
        b"2026-09-23 10:00:%02d.%03d <1008b5070209004f00\n" % (i // 1000 % 60, i % 1000)
        for i in range(1000)
    )

    records = RawRecordSplitter().feed(data, flush=True)

    assert len(records) == 1000
    assert scans <= 3
