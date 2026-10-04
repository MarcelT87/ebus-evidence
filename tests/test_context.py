import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest
import ebus_evidence.context as context_module

from ebus_evidence.context import (
    ContextCaptureManager,
    ContextError,
    context_metadata_scope,
    context_should_trigger,
    validate_capture_metadata,
)
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.watch import run_watch


def _record(timestamp: str, payload: str = "1008b50702090000") -> bytes:
    return f"{timestamp} <{payload}\n".encode("ascii")


def _event(timestamp: str, value: int) -> dict:
    return {
        "check_id": "rare",
        "timestamp": {
            "raw": timestamp,
            "utc": None,
            "display": None,
        },
        "source": "f1",
        "target": "08",
        "pbsb": "b509",
        "request": "05540200ba08",
        "response": "080201ba0820000000" if value else "080201ba0800000000",
        "value_status": "decoded",
        "value": value,
    }


def _profile() -> dict:
    return {
        "name": "context-test",
        "version": 1,
        "checks": [
            {
                "id": "rare",
                "description": "Rare value",
                "match": {},
                "context": {
                    "when": {"value_nonzero": True},
                    "before_seconds": 2,
                    "after_seconds": 2,
                },
            }
        ],
    }


def _metadata(directory):
    return [json.loads(path.read_text()) for path in sorted(directory.glob("*.json"))]


def test_continuous_triggers_split_and_keep_every_record_and_trigger(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())
    start = datetime(2026, 10, 1, 10)
    for second in range(3600):
        timestamp = (start + timedelta(seconds=second)).strftime("%Y-%m-%d %H:%M:%S.000")
        manager.observe(_record(timestamp))
        manager.trigger_event(_event(timestamp, 32))
        for session in manager.active.values():
            assert len(session.triggers) <= context_module.MAX_CONTEXT_TRIGGERS
            assert session.raw_bytes <= context_module.MAX_CONTEXT_BYTES
    manager.finish()
    metadata = _metadata(tmp_path)
    assert len(metadata) > 1
    assert sum(m["trigger_count"] for m in metadata) == 3600
    assert sum(m["record_count"] for m in metadata) == 3600
    previous = None
    for m in metadata:
        validate_capture_metadata(m)
        assert m["continuation_of"] == previous
        assert m["post_window_complete"] is False
        previous = m["raw_file"]
    assert {m["capture_end_reason"] for m in metadata} == {"trigger_limit", "collection_stopped"}


@pytest.mark.parametrize("limit_name,limit_value,reason", [
    ("MAX_CONTEXT_SECONDS", 2, "duration_limit"),
    ("MAX_CONTEXT_RECORDS", 2, "record_limit"),
    ("MAX_CONTEXT_BYTES", 90, "byte_limit"),
])
def test_context_segments_preserve_post_window_without_new_trigger(
    tmp_path, monkeypatch, limit_name, limit_value, reason
):
    monkeypatch.setattr(context_module, limit_name, limit_value)
    profile = _profile()
    profile["checks"][0]["context"]["before_seconds"] = 0
    profile["checks"][0]["context"]["after_seconds"] = 6
    manager = ContextCaptureManager(tmp_path, profile)
    for second in range(8):
        timestamp = f"2026-10-01 10:00:0{second}.000"
        manager.observe(_record(timestamp))
        if second == 0:
            manager.trigger_event(_event(timestamp, 32))
    metadata = _metadata(tmp_path)
    assert len(metadata) > 1
    assert sum(m["record_count"] for m in metadata) == 7
    assert sum(m["trigger_count"] for m in metadata) == 1
    assert metadata[0]["capture_end_reason"] == reason
    assert metadata[-1]["capture_end_reason"] == "post_window_complete"
    assert metadata[-1]["post_window_complete"] is True
    for m in metadata[1:]:
        assert m["continuation_of"] is not None
        assert m["pre_window_complete"] is False
    for m in metadata:
        validate_capture_metadata(m)
        assert (tmp_path / m["raw_file"]).stat().st_size <= context_module.MAX_CONTEXT_BYTES


@pytest.mark.parametrize("limit_name,limit_value", [
    ("MAX_RING_RECORDS", 2), ("MAX_RING_BYTES", 90),
])
def test_ring_limits_retain_incomplete_pre_window_metadata(
    tmp_path, monkeypatch, limit_name, limit_value
):
    monkeypatch.setattr(context_module, limit_name, limit_value)
    manager = ContextCaptureManager(tmp_path, _profile())
    # Repeated timestamps must not defeat the memory bounds.
    for _ in range(100):
        manager.observe(_record("2026-10-01 10:00:00.000"))
    assert len(manager.buffer) <= context_module.MAX_RING_RECORDS
    assert manager.buffer_bytes <= context_module.MAX_RING_BYTES
    manager.observe(_record("2026-10-01 10:00:02.000"))
    manager.trigger_event(_event("2026-10-01 10:00:02.000", 32))
    manager.finish()
    assert _metadata(tmp_path)[0]["pre_window_complete"] is False


def test_backward_clock_jump_closes_context_as_incomplete(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())
    manager.observe(_record("2026-10-01 10:00:02.000"))
    manager.trigger_event(_event("2026-10-01 10:00:02.000", 32))
    manager.observe(_record("2026-10-01 10:00:01.000"))
    metadata = _metadata(tmp_path)[0]
    assert metadata["capture_end_reason"] == "clock_regression"
    assert metadata["post_window_complete"] is False
    assert not manager.active


def test_bounded_context_metadata_rejects_unsafe_links_and_false_completeness(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())
    manager.observe(_record("2026-10-01 10:00:02.000"))
    manager.trigger_event(_event("2026-10-01 10:00:02.000", 32))
    manager.finish()
    metadata = _metadata(tmp_path)[0]
    with pytest.raises(ContextError, match="safe raw filename"):
        validate_capture_metadata({**metadata, "continuation_of": "../private.raw"})
    with pytest.raises(ContextError, match="contradicts"):
        validate_capture_metadata({**metadata, "post_window_complete": True})


def test_context_predicate_only_triggers_nonzero_value():
    context = _profile()["checks"][0]["context"]
    assert context_should_trigger(_event("2026-10-01 10:00:00.000", 0), context) is False
    assert context_should_trigger(_event("2026-10-01 10:00:00.000", 32), context) is True


def test_context_capture_writes_pre_and_post_records(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())

    for second in range(3):
        manager.observe(_record(f"2026-10-01 10:00:0{second}.000"))

    assert manager.trigger_event(_event("2026-10-01 10:00:02.000", 32)) is True

    manager.observe(_record("2026-10-01 10:00:03.000"))
    manager.observe(_record("2026-10-01 10:00:04.000"))
    manager.observe(_record("2026-10-01 10:00:05.000"))

    assert manager.completed == 1
    raw_files = list(tmp_path.glob("*.raw"))
    json_files = list(tmp_path.glob("*.json"))
    assert len(raw_files) == 1
    assert len(json_files) == 1

    lines = raw_files[0].read_text(encoding="ascii").splitlines()
    assert len(lines) == 5
    assert "10:00:00.000" in lines[0]
    assert "10:00:04.000" in lines[-1]

    metadata = json.loads(json_files[0].read_text(encoding="utf-8"))
    assert metadata["format"] == "ebus-evidence-context-v1"
    assert metadata["check_id"] == "rare"
    assert metadata["trigger_count"] == 1
    assert metadata["pre_window_complete"] is True
    assert metadata["post_window_complete"] is True
    assert metadata["record_count"] == 5
    assert metadata["raw_file"] == raw_files[0].name


def test_overlapping_context_triggers_are_coalesced(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())

    manager.observe(_record("2026-10-01 10:00:00.000"))
    manager.observe(_record("2026-10-01 10:00:01.000"))
    manager.observe(_record("2026-10-01 10:00:02.000"))
    manager.trigger_event(_event("2026-10-01 10:00:02.000", 32))

    manager.observe(_record("2026-10-01 10:00:03.000"))
    manager.trigger_event(_event("2026-10-01 10:00:03.000", 64))

    manager.observe(_record("2026-10-01 10:00:04.000"))
    manager.observe(_record("2026-10-01 10:00:05.000"))
    manager.observe(_record("2026-10-01 10:00:06.000"))

    assert manager.triggered == 2
    assert manager.completed == 1
    metadata = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["trigger_count"] == 2
    assert metadata["post_window_complete"] is True


def test_watch_integration_captures_real_ba08_nonzero(tmp_path, monkeypatch):
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 09:59:59.000"))
    context_dir = tmp_path / "contexts"
    profile = load_profile("hw5103-open-evidence")

    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            with raw.open("ab") as handle:
                handle.write(
                    _record(
                        "2026-10-01 10:00:00.000",
                        "f108b50905540200ba080000080201ba0820000000",
                    )
                )
                handle.write(_record("2026-10-01 10:00:01.000"))

    monkeypatch.setattr("ebus_evidence.watch.time.sleep", fake_sleep)

    stats = run_watch(
        raw,
        profile,
        seconds=0.01,
        context_dir=context_dir,
    )

    assert stats.context_triggers == 1
    assert stats.context_captures == 1
    metadata = json.loads(next(context_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["check_id"] == "hmu_ba08_variants"
    assert metadata["triggers"][0]["value"] == 32
    assert metadata["post_window_complete"] is False


def test_context_bundle_does_not_overwrite_existing_same_trigger(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())
    manager.observe(_record("2026-10-01 10:00:00.000"))
    manager.observe(_record("2026-10-01 10:00:01.000"))
    manager.observe(_record("2026-10-01 10:00:02.000"))
    manager.trigger_event(_event("2026-10-01 10:00:02.000", 32))
    manager.finish()

    manager2 = ContextCaptureManager(tmp_path, _profile())
    manager2.observe(_record("2026-10-01 10:00:00.000"))
    manager2.observe(_record("2026-10-01 10:00:01.000"))
    manager2.observe(_record("2026-10-01 10:00:02.000"))
    manager2.trigger_event(_event("2026-10-01 10:00:02.000", 32))
    manager2.finish()

    assert len(list(tmp_path.glob("*.raw"))) == 2
    assert len(list(tmp_path.glob("*.json"))) == 2


def test_final_tail_record_can_complete_watch_context_window(tmp_path, monkeypatch):
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 09:57:00.000"))
    context_dir = tmp_path / "contexts"
    profile = load_profile("hw5103-open-evidence")

    calls = {"count": 0}

    def fake_sleep(_seconds):
        calls["count"] += 1
        if calls["count"] == 1:
            with raw.open("ab") as handle:
                handle.write(_record("2026-10-01 09:58:00.000"))
                handle.write(_record("2026-10-01 09:59:00.000"))
                handle.write(
                    _record(
                        "2026-10-01 10:00:00.000",
                        "f108b50905540200ba080000080201ba0820000000",
                    )
                )
                handle.write(_record("2026-10-01 10:00:30.000"))
                handle.write(_record("2026-10-01 10:02:59.000"))
                handle.write(_record("2026-10-01 10:03:01.000"))

    monkeypatch.setattr("ebus_evidence.watch.time.sleep", fake_sleep)

    stats = run_watch(
        raw,
        profile,
        seconds=0.01,
        context_dir=context_dir,
    )

    assert stats.context_triggers == 1
    assert stats.context_captures == 1
    metadata = json.loads(next(context_dir.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["check_id"] == "hmu_ba08_variants"
    assert metadata["post_window_complete"] is True
    assert metadata["record_count"] == 5


def test_pre_window_complete_uses_observation_start_not_exact_boundary_record(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())

    manager.observe(_record("2026-10-01 10:00:00.250"))
    manager.observe(_record("2026-10-01 10:00:01.500"))
    manager.observe(_record("2026-10-01 10:00:02.750"))
    manager.observe(_record("2026-10-01 10:00:03.500"))

    assert manager.trigger_event(
        _event("2026-10-01 10:00:03.500", 32)
    ) is True
    manager.finish()

    metadata = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["pre_window_complete"] is True


def test_pre_window_incomplete_when_collection_started_too_late(tmp_path):
    manager = ContextCaptureManager(tmp_path, _profile())

    manager.observe(_record("2026-10-01 10:00:02.500"))
    assert manager.trigger_event(
        _event("2026-10-01 10:00:03.000", 32)
    ) is True
    manager.finish()

    metadata = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert metadata["pre_window_complete"] is False


def _write_context_metadata(path, *, profile_name: str, profile_version: int):
    path.write_text(
        json.dumps(
            {
                "format": "ebus-evidence-context-v1",
                "profile": profile_name,
                "profile_version": profile_version,
                "check_id": "rare",
                "description": "Rare value",
                "before_seconds": 0,
                "after_seconds": 0,
                "pre_window_complete": True,
                "post_window_complete": True,
                "trigger_count": 1,
                "triggers": [],
                "record_count": 0,
                "raw_file": path.with_suffix(".raw").name,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def test_context_scope_separates_historical_profile_versions(tmp_path):
    current_profile = {**_profile(), "version": 3}
    _write_context_metadata(
        tmp_path / "old.json",
        profile_name=current_profile["name"],
        profile_version=2,
    )
    _write_context_metadata(
        tmp_path / "current.json",
        profile_name=current_profile["name"],
        profile_version=3,
    )

    scope = context_metadata_scope(tmp_path, current_profile)

    assert [path.name for path in scope.current] == ["current.json"]
    assert [path.name for path in scope.historical] == ["old.json"]


def test_context_scope_rejects_future_profile_version(tmp_path):
    current_profile = {**_profile(), "version": 3}
    _write_context_metadata(
        tmp_path / "future.json",
        profile_name=current_profile["name"],
        profile_version=4,
    )

    import pytest

    with pytest.raises(ContextError, match="newer than active"):
        context_metadata_scope(tmp_path, current_profile)
