from pathlib import Path

from ebus_evidence.input.raw_file import (
    parse_record,
    resolve_raw_sources,
    split_records,
    unescape_wire,
)


FIXTURE = Path(__file__).parent / "fixtures" / "sample.raw"


def test_unescape_wire_handles_a9_and_aa():
    assert unescape_wire(bytes.fromhex("01a90002a90103")) == bytes.fromhex("01a902aa03")


def test_parser_keeps_request_length_byte():
    frame = parse_record(b"2026-09-23 10:00:00.000 <1008b50702090000")
    assert frame.source == "10"
    assert frame.target == "08"
    assert frame.pbsb == "b507"
    assert frame.request == "020900"
    assert frame.initiated_by_ebusd is False


def test_parser_extracts_passive_response():
    frame = parse_record(
        b"2026-10-01 10:00:00.000 <f108b50905540200a80e0000080201a80e0000b040"
    )
    assert frame.request == "05540200a80e"
    assert frame.response == "080201a80e0000b040"


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

    first = b"2026-10-01 10:00:00.000 <1008b50702090000"
    second = b"2026-10-01 10:00:01.000 <1008b50702090000"
    records, tail = split_record_buffer(first + b"\n" + second)

    assert records == [first]
    assert tail == second

    final, tail = split_record_buffer(tail, flush=True)
    assert final == [second]
    assert tail == b""
