import json

import pytest

from ebus_evidence.state import (
    EvidenceStateStore,
    StateError,
    load_state,
    new_state,
    update_observation_frame,
    update_observation_non_frame,
    update_observation_skip,
    update_state,
)


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


def test_state_checkpoint_persists_and_can_be_cleared(tmp_path):
    path = tmp_path / "state.json"
    store = EvidenceStateStore.open(path, PROFILE)

    checkpoint = {
        "device": 11,
        "inode": 22,
        "offset": 333,
        "anchor_start": 77,
        "anchor_sha256": "a" * 64,
    }
    assert store.set_checkpoint(checkpoint) is True

    reloaded = EvidenceStateStore.open(path, PROFILE)
    assert reloaded.checkpoint == checkpoint

    reloaded.clear_checkpoint(reason="test reset")
    again = EvidenceStateStore.open(path, PROFILE)
    assert again.checkpoint is None
    assert len(again.state["continuity"]["resets"]) == 1
    assert again.state["continuity"]["resets"][0]["reason"] == "test reset"


def test_old_state_without_checkpoint_is_backward_compatible(tmp_path):
    path = tmp_path / "state.json"
    state = new_state(PROFILE)
    state.pop("checkpoint")
    state.pop("continuity")
    path.write_text(json.dumps(state), encoding="utf-8")

    loaded = load_state(path, PROFILE)
    assert loaded["checkpoint"] is None
    assert loaded["continuity"]["resets"] == []


def test_legacy_checkpoint_without_anchor_is_still_accepted(tmp_path):
    path = tmp_path / "state.json"
    state = new_state(PROFILE)
    state["checkpoint"] = {"device": 1, "inode": 2, "offset": 3}
    path.write_text(json.dumps(state), encoding="utf-8")

    loaded = load_state(path, PROFILE)
    assert loaded["checkpoint"] == {"device": 1, "inode": 2, "offset": 3}


def test_state_tracks_observation_scope_independently_of_matches():
    state = new_state(PROFILE)
    timestamp = {
        "raw": "2026-10-01 21:00:00.000",
        "utc": "2026-10-01T21:00:00.000Z",
        "display": "2026-10-01T23:00:00.000+02:00",
    }

    update_observation_frame(state, timestamp, initiated_by_ebusd=False)
    update_observation_frame(state, timestamp, initiated_by_ebusd=True)
    update_observation_non_frame(state)
    update_observation_skip(state)

    observation = state["observation"]
    assert observation["frames_seen"] == 2
    assert observation["passive_frames"] == 1
    assert observation["ebusd_initiated_frames"] == 1
    assert observation["non_frames"] == 1
    assert observation["skipped"] == 1
    assert observation["first_frame_timestamp"] == timestamp
    assert observation["last_frame_timestamp"] == timestamp
    assert state["total_events"] == 0


def test_old_state_without_observation_is_backward_compatible(tmp_path):
    path = tmp_path / "state.json"
    state = new_state(PROFILE)
    state.pop("observation")
    path.write_text(json.dumps(state), encoding="utf-8")

    loaded = load_state(path, PROFILE)
    assert loaded["observation"]["frames_seen"] == 0
    assert loaded["observation"]["passive_frames"] == 0
    assert loaded["observation"]["ebusd_initiated_frames"] == 0
