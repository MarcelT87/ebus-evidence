import hashlib
import json
import zipfile

import pytest

from ebus_evidence.bundle import BundleError, create_bundle, shared_state
from ebus_evidence.state import new_state, save_state, update_state


PROFILE = {
    "name": "bundle-test",
    "version": 7,
    "checks": [
        {
            "id": "rare",
            "description": "Rare evidence",
            "match": {"source": "f1", "target": "08", "pbsb": "b509"},
        }
    ],
}


def _event():
    return {
        "check_id": "rare",
        "timestamp": {
            "raw": "2026-10-01 10:00:00.000",
            "utc": "2026-10-01T10:00:00.000Z",
            "display": "2026-10-01T12:00:00.000+02:00",
        },
        "response": "080201ba0820000000",
        "value_status": "decoded",
        "value": 32,
    }


def _write_state(path):
    state = new_state(PROFILE)
    update_state(state, _event())
    state["checkpoint"] = {
        "device": 64518,
        "inode": 393828,
        "offset": 123456,
        "anchor_start": 123200,
        "anchor_sha256": "a" * 64,
    }
    state["continuity"]["resets"].append(
        {"at": "2026-10-01T10:01:00Z", "reason": "private local reason"}
    )
    save_state(path, state)
    return state


def _write_context(directory):
    directory.mkdir()
    raw_name = "20261001T100000.000_rare_0001.raw"
    json_name = "20261001T100000.000_rare_0001.json"
    raw = (
        b"2026-10-01 09:59:59.000 <1008b50702090000\n"
        b"2026-10-01 10:00:00.000 <f108b50905540200ba080000080201ba0820000000\n"
    )
    (directory / raw_name).write_bytes(raw)
    metadata = {
        "format": "ebus-evidence-context-v1",
        "profile": PROFILE["name"],
        "profile_version": PROFILE["version"],
        "check_id": "rare",
        "description": "Rare evidence",
        "before_seconds": 120.0,
        "after_seconds": 180.0,
        "pre_window_complete": True,
        "post_window_complete": True,
        "trigger_count": 1,
        "triggers": [_event()],
        "record_count": 2,
        "raw_file": raw_name,
    }
    (directory / json_name).write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def test_shared_state_excludes_local_resume_metadata():
    state = new_state(PROFILE)
    state["checkpoint"] = {
        "device": 1,
        "inode": 2,
        "offset": 3,
        "anchor_start": 0,
        "anchor_sha256": "b" * 64,
    }
    state["continuity"]["resets"].append(
        {"at": "2026-10-01T10:00:00Z", "reason": "local detail"}
    )

    shared = shared_state(state)
    encoded = json.dumps(shared)

    assert shared["format"] == "ebus-evidence-shared-state-v1"
    assert shared["continuity_reset_count"] == 1
    assert "checkpoint" not in shared
    assert "device" not in encoded
    assert "inode" not in encoded
    assert "anchor_sha256" not in encoded
    assert "local detail" not in encoded


def test_bundle_is_deterministic_and_checksums_verify(tmp_path):
    state_path = tmp_path / "state.json"
    context_dir = tmp_path / "contexts"
    _write_state(state_path)
    _write_context(context_dir)

    first = tmp_path / "first.zip"
    second = tmp_path / "second.zip"

    result1 = create_bundle(
        first,
        PROFILE,
        state_path=state_path,
        context_dir=context_dir,
    )
    result2 = create_bundle(
        second,
        PROFILE,
        state_path=state_path,
        context_dir=context_dir,
    )

    assert first.read_bytes() == second.read_bytes()
    assert result1["sha256"] == result2["sha256"]

    with zipfile.ZipFile(first) as archive:
        names = sorted(archive.namelist())
        assert names == sorted(
            [
                "checksums.json",
                "contexts/20261001T100000.000_rare_0001.json",
                "contexts/20261001T100000.000_rare_0001.raw",
                "evidence/state.json",
                "manifest.json",
                "profile.yaml",
            ]
        )

        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["format"] == "ebus-evidence-bundle-v1"
        assert manifest["evidence_state_included"] is True
        assert manifest["context_metadata_count"] == 1
        assert manifest["context_raw_count"] == 1
        assert manifest["privacy"]["absolute_paths_included"] is False
        assert manifest["privacy"]["resume_checkpoint_included"] is False
        assert manifest["privacy"]["full_raw_log_included"] is False
        assert (
            manifest["privacy"]["context_raw_may_contain_device_specific_bus_data"]
            is True
        )
        assert manifest["privacy"]["review_context_raw_before_public_sharing"] is True

        shared = json.loads(archive.read("evidence/state.json"))
        assert shared["total_events"] == 1
        assert "checkpoint" not in shared

        checksums = json.loads(archive.read("checksums.json"))["sha256"]
        for name, expected in checksums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


def test_bundle_can_exclude_context_raw(tmp_path):
    context_dir = tmp_path / "contexts"
    _write_context(context_dir)
    output = tmp_path / "metadata-only.zip"

    result = create_bundle(
        output,
        PROFILE,
        context_dir=context_dir,
        include_context_raw=False,
    )

    with zipfile.ZipFile(output) as archive:
        assert "contexts/20261001T100000.000_rare_0001.json" in archive.namelist()
        assert "contexts/20261001T100000.000_rare_0001.raw" not in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["context_metadata_count"] == 1
        assert manifest["context_raw_count"] == 0
        assert manifest["context_raw_included"] is False

    assert result["manifest"]["context_raw_count"] == 0


def test_bundle_rejects_missing_explicit_state(tmp_path):
    with pytest.raises(BundleError, match="evidence state not found"):
        create_bundle(
            tmp_path / "bundle.zip",
            PROFILE,
            state_path=tmp_path / "missing.json",
        )


def test_bundle_requires_some_evidence_source(tmp_path):
    with pytest.raises(BundleError, match="requires --state, --context-dir, or both"):
        create_bundle(tmp_path / "bundle.zip", PROFILE)


def test_context_only_empty_directory_is_rejected(tmp_path):
    context_dir = tmp_path / "contexts"
    context_dir.mkdir()

    with pytest.raises(BundleError, match="no evidence found"):
        create_bundle(
            tmp_path / "bundle.zip",
            PROFILE,
            context_dir=context_dir,
        )
