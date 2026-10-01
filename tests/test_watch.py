from pathlib import Path

from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.watch import RawLogFollower, frame_events
from ebus_evidence.input.raw_file import parse_record


ROOT = Path(__file__).parents[1]


def _record(timestamp: str) -> bytes:
    return f"{timestamp} <1008b50702090000\n".encode("ascii")


def test_follower_reads_only_new_records_by_default(tmp_path):
    path = tmp_path / "ebusd.raw"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    follower = RawLogFollower(path)
    follower.start()
    assert follower.poll() == []

    with path.open("ab") as handle:
        handle.write(_record("2026-10-01 10:00:01.000"))
        handle.write(_record("2026-10-01 10:00:02.000"))

    records = follower.poll()
    assert len(records) == 1
    assert b"10:00:01.000" in records[0]

    final = follower.finish()
    assert len(final) == 1
    assert b"10:00:02.000" in final[0]


def test_follower_survives_rename_create_rotation(tmp_path):
    path = tmp_path / "ebusd.raw"
    old = tmp_path / "ebusd.raw.old"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    follower = RawLogFollower(path)
    follower.start()

    with path.open("ab") as handle:
        handle.write(_record("2026-10-01 10:00:01.000"))
    assert follower.poll() == []

    path.rename(old)
    path.write_bytes(
        _record("2026-10-01 10:00:02.000")
        + _record("2026-10-01 10:00:03.000")
    )

    records = follower.poll()
    assert follower.rotations == 1
    assert len(records) == 2
    assert b"10:00:01.000" in records[0]
    assert b"10:00:02.000" in records[1]

    final = follower.finish()
    assert len(final) == 1
    assert b"10:00:03.000" in final[0]


def test_watch_event_decodes_profile_value():
    profile = load_profile("hw5103-open-evidence")
    frame = parse_record(
        b"2026-10-01 10:00:00.000 <f108b50905540200ba080000080201ba0820000000"
    )

    events = frame_events(
        frame,
        profile,
        source_timezone="UTC",
        display_timezone="Europe/Berlin",
    )

    assert len(events) == 1
    event = events[0]
    assert event["check_id"] == "hmu_ba08_variants"
    assert event["value_status"] == "decoded"
    assert event["value"] == 32
    assert event["timestamp"]["display"] == "2026-10-01T12:00:00.000+02:00"
