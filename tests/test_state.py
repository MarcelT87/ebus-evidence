import json

import pytest

from ebus_evidence.state import EvidenceStateStore, StateError, load_state, new_state, update_state


PROFILE = {
    "name": "test-profile",
    "version": 3,
    "checks": [
        {"id": "check_a", "description": "Check A", "match": {}},
    ],
}


def _event(value=32):
    return {
        "check_id": "check_a",
        "timestamp": {
            "raw": "2026-10-01 21:00:00.000",
            "utc": "2026-10-01T21:00:00.000Z",
            "display": "2026-10-01T23:00:00.000+02:00",
        },
        "response": "080201ba0820000000",
        "value_status": "decoded",
        "value": value,
    }


def test_state_aggregates_events():
    state = new_state(PROFILE)
    update_state(state, _event())
    update_state(state, _event())

    check = state["checks"]["check_a"]
    assert state["total_events"] == 2
    assert check["matches"] == 2
    assert check["responses"]["080201ba0820000000"]["count"] == 2
    assert check["values"]["32"]["value"] == 32
    assert check["values"]["32"]["count"] == 2
    assert check["value_status"]["decoded"] == 2


def test_state_store_persists_and_reloads(tmp_path):
    path = tmp_path / "state.json"
    store = EvidenceStateStore.open(path, PROFILE)
    store.add(_event())

    reloaded = EvidenceStateStore.open(path, PROFILE)
    assert reloaded.total_events == 1
    assert reloaded.state["checks"]["check_a"]["matches"] == 1
    json.loads(path.read_text(encoding="utf-8"))
    assert not (tmp_path / "state.json.tmp").exists()


def test_state_rejects_different_profile_version(tmp_path):
    path = tmp_path / "state.json"
    state = new_state(PROFILE)
    path.write_text(json.dumps(state), encoding="utf-8")

    incompatible = dict(PROFILE)
    incompatible["version"] = 4
    with pytest.raises(StateError, match="version mismatch"):
        load_state(path, incompatible)


def test_state_rejects_different_profile_name(tmp_path):
    path = tmp_path / "state.json"
    state = new_state(PROFILE)
    path.write_text(json.dumps(state), encoding="utf-8")

    incompatible = dict(PROFILE)
    incompatible["name"] = "other-profile"
    with pytest.raises(StateError, match="profile mismatch"):
        load_state(path, incompatible)
