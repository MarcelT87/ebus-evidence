import hashlib
import json
import zipfile

import pytest

from ebus_evidence.bundle import BundleError, create_bundle, shared_state, verify_bundle
from ebus_evidence.state import (
    EvidenceStateStore,
    new_state,
    save_state,
    update_observation_frame,
    update_state,
)
from ebus_evidence.system_identity import build_system_document, parse_scan_result


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


def _upgraded_profile():
    return {
        **PROFILE,
        "version": PROFILE["version"] + 1,
        "checks": PROFILE["checks"]
        + [
            {
                "id": "new_check",
                "description": "New check",
                "match": {"source": "03", "target": "76", "pbsb": "b512"},
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
    update_observation_frame(
        state,
        _event()["timestamp"],
        initiated_by_ebusd=False,
    )
    update_state(state, _event())
    state["checkpoint"] = {
        "device": 1001,
        "inode": 2002,
        "offset": 123456,
        "anchor_start": 123200,
        "anchor_sha256": "a" * 64,
    }
    state["continuity"]["resets"].append(
        {"at": "2026-10-01T10:01:00Z", "reason": "private local reason"}
    )
    save_state(path, state)
    return state


def _write_system(path):
    devices = parse_scan_result(
        "08;Vaillant;HMU00;0902;5103;ignored;private-extra\n"
        "15;Vaillant;CTLV2;0515;1104;ignored-too\n"
    )
    document = build_system_document(
        devices,
        declared_manufacturer="Vaillant",
        declared_model="TEST-MODEL",
    )
    path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return document


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
        include_context_raw=True,
    )
    result2 = create_bundle(
        second,
        PROFILE,
        state_path=state_path,
        context_dir=context_dir,
        include_context_raw=True,
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
        provenance = manifest["provenance"]
        assert provenance["tool_runtime"]["algorithm"] == "ebus-evidence-runtime-sha256-v1"
        assert len(provenance["tool_runtime"]["sha256"]) == 64
        assert manifest["evidence_state_included"] is True
        assert manifest["context_metadata_count"] == 1
        assert manifest["context_raw_count"] == 1
        assert manifest["privacy"]["absolute_paths_included"] is False
        assert manifest["privacy"]["resume_checkpoint_included"] is False
        assert manifest["privacy"]["full_raw_log_included"] is False
        assert manifest["privacy"]["absolute_timestamps_included"] is True
        assert (
            manifest["privacy"]["context_raw_may_contain_device_specific_bus_data"]
            is True
        )
        assert manifest["privacy"]["review_context_raw_before_public_sharing"] is True

        shared = json.loads(archive.read("evidence/state.json"))
        assert shared["total_events"] == 1
        assert shared["observation"]["frames_seen"] == 1
        assert shared["observation"]["passive_frames"] == 1
        assert shared["observation"]["ebusd_initiated_frames"] == 0
        assert shared["observation"]["first_frame_timestamp"]["raw"] == "2026-10-01 10:00:00.000"
        assert "checkpoint" not in shared

        checksums = json.loads(archive.read("checksums.json"))["sha256"]
        assert provenance["profile_sha256"] == checksums["profile.yaml"]
        if provenance["git"] is not None:
            assert len(provenance["git"]["commit"]) in {40, 64}
            assert isinstance(provenance["git"]["dirty"], bool)
        for name, expected in checksums.items():
            assert hashlib.sha256(archive.read(name)).hexdigest() == expected


def test_bundle_excludes_context_raw_by_default(tmp_path):
    context_dir = tmp_path / "contexts"
    _write_context(context_dir)
    output = tmp_path / "metadata-only.zip"

    result = create_bundle(
        output,
        PROFILE,
        context_dir=context_dir,
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


def test_verify_accepts_valid_bundle(tmp_path):
    state_path = tmp_path / "state.json"
    context_dir = tmp_path / "contexts"
    _write_state(state_path)
    _write_context(context_dir)
    output = tmp_path / "bundle.zip"

    created = create_bundle(
        output,
        PROFILE,
        state_path=state_path,
        context_dir=context_dir,
        include_context_raw=True,
    )
    verified = verify_bundle(output)

    assert verified["valid"] is True
    assert verified["sha256"] == created["sha256"]
    assert verified["profile"] == PROFILE["name"]
    assert verified["profile_version"] == PROFILE["version"]
    assert verified["provenance"] == created["manifest"]["provenance"]
    assert verified["state_included"] is True
    assert verified["context_metadata_count"] == 1
    assert verified["context_raw_count"] == 1
    assert verified["deterministic_layout"] is True


def test_bundle_preserves_historical_epoch_and_excludes_old_contexts(tmp_path):
    state_path = tmp_path / "state.json"
    context_dir = tmp_path / "contexts"
    _write_state(state_path)
    _write_context(context_dir)

    upgraded = _upgraded_profile()
    rolled = EvidenceStateStore.open(
        state_path,
        upgraded,
        allow_profile_rollover=True,
    )
    assert rolled.rolled_over_from == PROFILE["version"]
    assert rolled.state["observation"]["frames_seen"] == 0
    assert rolled.historical_frames == 1

    output = tmp_path / "rolled.zip"
    created = create_bundle(
        output,
        upgraded,
        state_path=state_path,
        context_dir=context_dir,
        include_context_raw=True,
    )

    assert created["historical_context_metadata_excluded"] == 1
    assert created["manifest"]["context_metadata_count"] == 0
    assert created["manifest"]["context_raw_count"] == 0

    with zipfile.ZipFile(output) as archive:
        assert not any(name.startswith("contexts/") for name in archive.namelist())
        shared = json.loads(archive.read("evidence/state.json"))
        assert shared["profile_version"] == upgraded["version"]
        assert shared["observation"]["frames_seen"] == 0
        assert len(shared["epochs"]) == 1
        epoch = shared["epochs"][0]
        assert epoch["profile_version"] == PROFILE["version"]
        assert epoch["observation"]["frames_seen"] == 1
        assert epoch["checks"]["rare"]["matches"] == 1
        assert "checkpoint" not in json.dumps(shared)

    verified = verify_bundle(output)
    assert verified["valid"] is True
    assert verified["historical_epoch_count"] == 1
    assert verified["historical_frames"] == 1
    assert verified["context_metadata_count"] == 0
    assert verified["context_raw_count"] == 0


def test_read_only_rollover_preview_bundle_is_deterministic(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    before = state_path.read_bytes()
    upgraded = _upgraded_profile()

    first = tmp_path / "preview-one.zip"
    second = tmp_path / "preview-two.zip"

    result1 = create_bundle(first, upgraded, state_path=state_path)
    result2 = create_bundle(second, upgraded, state_path=state_path)

    assert first.read_bytes() == second.read_bytes()
    assert result1["sha256"] == result2["sha256"]
    assert state_path.read_bytes() == before

    verified = verify_bundle(first)
    assert verified["valid"] is True
    assert verified["deterministic_layout"] is True
    assert verified["historical_epoch_count"] == 1
    assert verified["historical_frames"] == 1
    assert verified["observation"]["frames_seen"] == 0


def test_verify_accepts_legacy_shared_state_without_epoch_fields(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    current = tmp_path / "current-state-fields.zip"
    legacy = tmp_path / "legacy-state-fields.zip"
    create_bundle(current, PROFILE, state_path=state_path)

    with zipfile.ZipFile(current) as src:
        members = {name: src.read(name) for name in src.namelist()}

    state = json.loads(members["evidence/state.json"])
    state.pop("profile_fingerprint", None)
    state.pop("epochs", None)
    members["evidence/state.json"] = (
        json.dumps(state, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["evidence/state.json"] = hashlib.sha256(
        members["evidence/state.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    verified = verify_bundle(legacy)
    assert verified["valid"] is True
    assert verified["historical_epoch_count"] == 0
    assert verified["historical_frames"] == 0


def test_verify_rejects_epoch_that_is_not_older_than_active_profile(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    upgraded = _upgraded_profile()
    EvidenceStateStore.open(
        state_path,
        upgraded,
        allow_profile_rollover=True,
    )

    original = tmp_path / "valid-epoch.zip"
    invalid = tmp_path / "invalid-epoch.zip"
    create_bundle(original, upgraded, state_path=state_path)

    with zipfile.ZipFile(original) as src:
        members = {name: src.read(name) for name in src.namelist()}

    state = json.loads(members["evidence/state.json"])
    state["epochs"][0]["profile_version"] = upgraded["version"]
    members["evidence/state.json"] = (
        json.dumps(state, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["evidence/state.json"] = hashlib.sha256(
        members["evidence/state.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(invalid, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    with pytest.raises(BundleError, match="below active version"):
        verify_bundle(invalid)


def test_verify_rejects_tampered_member(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original.zip"
    tampered = tmp_path / "tampered.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src, zipfile.ZipFile(tampered, "w") as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if info.filename == "evidence/state.json":
                data = data.replace(b'"total_events": 1', b'"total_events": 9')
            dst.writestr(info, data)

    with pytest.raises(BundleError, match="checksum mismatch"):
        verify_bundle(tampered)


def test_verify_rejects_unsafe_member_path(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original.zip"
    unsafe = tmp_path / "unsafe.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src, zipfile.ZipFile(unsafe, "w") as dst:
        for info in src.infolist():
            dst.writestr(info, src.read(info.filename))
        dst.writestr("../escape.txt", b"nope")

    with pytest.raises(BundleError, match="unsafe bundle member path"):
        verify_bundle(unsafe)


def test_verify_allows_repacked_valid_bundle_but_flags_layout(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original.zip"
    repacked = tmp_path / "repacked.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src, zipfile.ZipFile(
        repacked, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        for name in reversed(src.namelist()):
            dst.writestr(name, src.read(name))

    verified = verify_bundle(repacked)
    assert verified["valid"] is True
    assert verified["deterministic_layout"] is False


def test_bundle_rejects_context_raw_filename_traversal(tmp_path):
    context_dir = tmp_path / "contexts"
    context_dir.mkdir()
    metadata = {
        "format": "ebus-evidence-context-v1",
        "profile": PROFILE["name"],
        "profile_version": PROFILE["version"],
        "check_id": "rare",
        "description": "Rare evidence",
        "before_seconds": 1,
        "after_seconds": 1,
        "pre_window_complete": True,
        "post_window_complete": True,
        "trigger_count": 1,
        "triggers": [_event()],
        "record_count": 1,
        "raw_file": "..\\escape.raw",
    }
    (context_dir / "bad.json").write_text(
        json.dumps(metadata),
        encoding="utf-8",
    )

    with pytest.raises(BundleError, match="invalid raw_file"):
        create_bundle(
            tmp_path / "bundle.zip",
            PROFILE,
            context_dir=context_dir,
            include_context_raw=False,
        )


def test_bundle_can_include_validated_system_identity(tmp_path):
    state_path = tmp_path / "state.json"
    system_path = tmp_path / "system.json"
    _write_state(state_path)
    expected_system = _write_system(system_path)

    output = tmp_path / "with-system.zip"
    create_bundle(
        output,
        PROFILE,
        state_path=state_path,
        system_path=system_path,
    )

    with zipfile.ZipFile(output) as archive:
        assert "system.json" in archive.namelist()
        bundled_system = json.loads(archive.read("system.json"))
        assert bundled_system == expected_system
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["system_identity_included"] is True

    verified = verify_bundle(output)
    assert verified["system_identity_included"] is True
    assert (
        verified["topology_signature_sha256"]
        == expected_system["topology_signature_sha256"]
    )


def test_bundle_rejects_system_identity_with_unapproved_device_field(tmp_path):
    state_path = tmp_path / "state.json"
    system_path = tmp_path / "system.json"
    _write_state(state_path)
    document = _write_system(system_path)
    document["devices"][0]["serial"] = "must-not-be-shared"
    system_path.write_text(json.dumps(document), encoding="utf-8")

    with pytest.raises(BundleError, match="address/manufacturer/id/sw/hw"):
        create_bundle(
            tmp_path / "invalid-system.zip",
            PROFILE,
            state_path=state_path,
            system_path=system_path,
        )


def test_verify_accepts_legacy_manifest_without_timestamp_privacy_flag(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "current.zip"
    legacy = tmp_path / "legacy.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src:
        members = {name: src.read(name) for name in src.namelist()}

    manifest = json.loads(members["manifest.json"])
    manifest["privacy"].pop("absolute_timestamps_included")
    members["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["manifest.json"] = hashlib.sha256(
        members["manifest.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    verified = verify_bundle(legacy)
    assert verified["valid"] is True
    assert verified["absolute_timestamps_included"] is None


def test_verify_accepts_legacy_bundle_without_provenance(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    current = tmp_path / "current-provenance.zip"
    legacy = tmp_path / "legacy-no-provenance.zip"
    create_bundle(current, PROFILE, state_path=state_path)

    with zipfile.ZipFile(current) as src:
        members = {name: src.read(name) for name in src.namelist()}

    manifest = json.loads(members["manifest.json"])
    manifest.pop("provenance")
    members["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["manifest.json"] = hashlib.sha256(
        members["manifest.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(legacy, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    verified = verify_bundle(legacy)
    assert verified["valid"] is True
    assert verified["provenance"] is None


def test_verify_rejects_profile_provenance_mismatch(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-provenance.zip"
    invalid = tmp_path / "invalid-provenance.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src:
        members = {name: src.read(name) for name in src.namelist()}

    manifest = json.loads(members["manifest.json"])
    manifest["provenance"]["profile_sha256"] = "0" * 64
    members["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["manifest.json"] = hashlib.sha256(
        members["manifest.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(invalid, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    with pytest.raises(BundleError, match="does not match profile.yaml"):
        verify_bundle(invalid)


def test_verify_rejects_invalid_runtime_provenance_digest(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-runtime-provenance.zip"
    invalid = tmp_path / "invalid-runtime-provenance.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src:
        members = {name: src.read(name) for name in src.namelist()}

    manifest = json.loads(members["manifest.json"])
    manifest["provenance"]["tool_runtime"]["sha256"] = "not-a-sha"
    members["manifest.json"] = (
        json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["manifest.json"] = hashlib.sha256(
        members["manifest.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(invalid, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    with pytest.raises(BundleError, match="tool runtime SHA-256 is invalid"):
        verify_bundle(invalid)


def test_verify_rejects_invalid_observation_counts(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-observation.zip"
    invalid = tmp_path / "invalid-observation.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as src:
        members = {name: src.read(name) for name in src.namelist()}

    state = json.loads(members["evidence/state.json"])
    state["observation"]["frames_seen"] = 9
    members["evidence/state.json"] = (
        json.dumps(state, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    checksums = json.loads(members["checksums.json"])
    checksums["sha256"]["evidence/state.json"] = hashlib.sha256(
        members["evidence/state.json"]
    ).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")

    with zipfile.ZipFile(invalid, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for name in sorted(members):
            dst.writestr(name, members[name])

    with pytest.raises(BundleError, match="must sum to frames_seen"):
        verify_bundle(invalid)


def test_bundle_can_explicitly_include_context_raw(tmp_path):
    context_dir = tmp_path / "contexts"
    _write_context(context_dir)
    output = tmp_path / "with-raw.zip"

    result = create_bundle(
        output,
        PROFILE,
        context_dir=context_dir,
        include_context_raw=True,
    )

    with zipfile.ZipFile(output) as archive:
        assert "contexts/20261001T100000.000_rare_0001.raw" in archive.namelist()
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["context_raw_count"] == 1
        assert manifest["context_raw_included"] is True
        assert (
            manifest["privacy"]["review_context_raw_before_public_sharing"]
            is True
        )

    assert result["manifest"]["context_raw_count"] == 1


def test_verify_reports_unsupported_zip_compression_as_bundle_error(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    output = tmp_path / "unknown-compression.zip"
    create_bundle(output, PROFILE, state_path=state_path)

    with zipfile.ZipFile(output) as archive:
        info = archive.getinfo("checksums.json")
        local_header_offset = info.header_offset

    data = bytearray(output.read_bytes())
    unknown_method = (99).to_bytes(2, "little")

    # Local file header compression method.
    assert data[local_header_offset : local_header_offset + 4] == b"PK\x03\x04"
    data[local_header_offset + 8 : local_header_offset + 10] = unknown_method

    # Matching central-directory entry compression method.
    position = 0
    patched_central = False
    while True:
        central = data.find(b"PK\x01\x02", position)
        if central < 0:
            break
        name_length = int.from_bytes(data[central + 28 : central + 30], "little")
        extra_length = int.from_bytes(data[central + 30 : central + 32], "little")
        comment_length = int.from_bytes(data[central + 32 : central + 34], "little")
        name_start = central + 46
        name = bytes(data[name_start : name_start + name_length])
        if name == b"checksums.json":
            data[central + 10 : central + 12] = unknown_method
            patched_central = True
            break
        position = name_start + name_length + extra_length + comment_length

    assert patched_central is True
    output.write_bytes(data)

    with pytest.raises(BundleError, match="cannot read bundle member checksums.json"):
        verify_bundle(output)



def _repack_bundle_member(source, target, name, data):
    with zipfile.ZipFile(source) as src:
        members = {member: src.read(member) for member in src.namelist()}
    members[name] = data
    checksums = json.loads(members["checksums.json"])
    checksums["sha256"][name] = hashlib.sha256(data).hexdigest()
    members["checksums.json"] = (
        json.dumps(checksums, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as dst:
        for member in sorted(members):
            dst.writestr(member, members[member])


def _shared_state_with_nested_check(state, depth, leaf_json="0"):
    shallow = {key: value for key, value in state.items() if key != "checks"}
    prefix = json.dumps(shallow, sort_keys=True)[:-1]
    nested = '{"x":' * depth + leaf_json + '}' * depth
    return (prefix + ',"checks":{"rare":' + nested + '}}').encode("utf-8")


def test_verify_rejects_excessively_nested_state(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-depth.zip"
    invalid = tmp_path / "invalid-depth.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as archive:
        state = json.loads(archive.read("evidence/state.json"))
    nested_state = _shared_state_with_nested_check(state, 80)
    _repack_bundle_member(
        original,
        invalid,
        "evidence/state.json",
        nested_state,
    )

    with pytest.raises(BundleError, match="maximum nesting depth"):
        verify_bundle(invalid)


def test_verify_deep_allowed_state_still_finds_forbidden_resume_fields(tmp_path):
    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-forbidden-depth.zip"
    invalid = tmp_path / "invalid-forbidden-depth.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as archive:
        state = json.loads(archive.read("evidence/state.json"))
    nested_state = _shared_state_with_nested_check(
        state,
        50,
        leaf_json='{"device":1}',
    )
    _repack_bundle_member(
        original,
        invalid,
        "evidence/state.json",
        nested_state,
    )

    with pytest.raises(BundleError, match="forbidden local resume fields: device"):
        verify_bundle(invalid)


def test_verify_wraps_json_recursion_error_as_bundle_error(tmp_path, monkeypatch):
    import ebus_evidence.bundle as bundle_module

    state_path = tmp_path / "state.json"
    _write_state(state_path)
    original = tmp_path / "original-json-recursion.zip"
    invalid = tmp_path / "invalid-json-recursion.zip"
    create_bundle(original, PROFILE, state_path=state_path)

    with zipfile.ZipFile(original) as archive:
        state = json.loads(archive.read("evidence/state.json"))
    state["checks"]["rare"]["recursion_marker"] = True
    state_bytes = (json.dumps(state, sort_keys=True) + "\n").encode("utf-8")
    _repack_bundle_member(
        original,
        invalid,
        "evidence/state.json",
        state_bytes,
    )

    real_loads = bundle_module.json.loads

    def loads_with_recursion(value, *args, **kwargs):
        if isinstance(value, str) and '"recursion_marker": true' in value:
            raise RecursionError("synthetic deeply nested JSON")
        return real_loads(value, *args, **kwargs)

    monkeypatch.setattr(bundle_module.json, "loads", loads_with_recursion)
    with pytest.raises(BundleError, match="structure is too deeply nested"):
        verify_bundle(invalid)


def test_create_bundle_rejects_excessively_nested_local_state(tmp_path):
    state_path = tmp_path / "state.json"
    state = _write_state(state_path)
    nested = 0
    for _ in range(80):
        nested = {"x": nested}
    state["checks"]["rare"]["deep"] = nested
    state_path.write_text(
        json.dumps(state, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    with pytest.raises(BundleError, match="evidence state exceeds maximum nesting depth"):
        create_bundle(
            tmp_path / "too-deep.zip",
            PROFILE,
            state_path=state_path,
        )



def test_create_bundle_rejects_cyclic_profile_structure(tmp_path):
    profile = {
        "name": "cyclic-profile",
        "version": 1,
        "checks": [
            {
                "id": "rare",
                "match": {"source": "f1", "target": "08", "pbsb": "b509"},
            }
        ],
    }
    profile["cycle"] = profile

    with pytest.raises(BundleError, match="repeated or cyclic container references"):
        create_bundle(tmp_path / "cyclic.zip", profile)
