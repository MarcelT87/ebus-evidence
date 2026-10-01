from pathlib import Path

from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.watch import RawLogFollower, frame_events, run_watch
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

    final, tail = follower.finish()
    assert final == []
    assert tail is not None
    assert b"10:00:02.000" in tail


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

    final, tail = follower.finish()
    assert final == []
    assert tail is not None
    assert b"10:00:03.000" in tail


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


def test_watch_tracks_completed_unparseable_records_by_reason(tmp_path, monkeypatch):
    path = tmp_path / "ebusd.raw"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            with path.open("ab") as handle:
                handle.write(b"2026-10-01 10:00:01.000 <a\n")
                handle.write(_record("2026-10-01 10:00:02.000"))

    monkeypatch.setattr("ebus_evidence.watch.time.sleep", fake_sleep)
    stats = run_watch(path, {"name": "none", "version": 1, "checks": []}, seconds=0.01)

    assert stats.skipped_records == 1
    assert stats.skip_reasons["master segment has an odd number of hex digits"] == 1


def test_unfinished_tail_is_not_counted_as_skipped(tmp_path):
    path = tmp_path / "ebusd.raw"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    follower = RawLogFollower(path)
    follower.start()
    with path.open("ab") as handle:
        handle.write(b"2026-10-01 10:00:01.000 <f108")

    _, tail = follower.finish()
    assert tail is not None


def test_watch_keeps_bounded_skip_samples(tmp_path, monkeypatch):
    path = tmp_path / "ebusd.raw"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            with path.open("ab") as handle:
                for second in range(1, 6):
                    handle.write(
                        f"2026-10-01 10:00:0{second}.000 <a\n".encode("ascii")
                    )
                handle.write(_record("2026-10-01 10:00:06.000"))

    monkeypatch.setattr("ebus_evidence.watch.time.sleep", fake_sleep)
    stats = run_watch(path, {"name": "none", "version": 1, "checks": []}, seconds=0.01)

    reason = "master segment has an odd number of hex digits"
    assert stats.skipped_records == 5
    assert stats.skip_reasons[reason] == 5
    assert len(stats.skip_samples[reason]) == 3
    assert "record=2026-10-01 10:00:01.000 <a" in stats.skip_samples[reason][0]


def test_watch_classifies_short_raw_fragments_as_non_frames(tmp_path, monkeypatch):
    path = tmp_path / "ebusd.raw"
    path.write_bytes(_record("2026-10-01 10:00:00.000"))

    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            with path.open("ab") as handle:
                handle.write(b"2026-10-01 10:00:01.000 <00\n")
                handle.write(b"2026-10-01 10:00:02.000 <01\n")
                handle.write(_record("2026-10-01 10:00:03.000"))

    monkeypatch.setattr("ebus_evidence.watch.time.sleep", fake_sleep)
    stats = run_watch(path, {"name": "none", "version": 1, "checks": []}, seconds=0.01)

    assert stats.non_frame_records == 2
    assert stats.non_frame_kinds["short_fragment"] == 2
    assert stats.skipped_records == 0
    assert len(stats.non_frame_samples["short_fragment"]) == 2
