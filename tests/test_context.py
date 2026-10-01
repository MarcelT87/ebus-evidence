import json
from pathlib import Path

from ebus_evidence.context import ContextCaptureManager, context_should_trigger
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
