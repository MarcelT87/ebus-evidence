from __future__ import annotations

import zipfile
import json
import hashlib
from copy import deepcopy

import pytest

import ebus_evidence.submission as submission
from ebus_evidence.bundle import create_bundle, verify_bundle
from ebus_evidence.cli import main
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.submission import SubmissionError, verify_submission_bundle


def test_segmented_contexts_export_deterministically_and_pass_submission(tmp_path, monkeypatch):
    from ebus_evidence.context import ContextCaptureManager
    import ebus_evidence.context as context_module

    monkeypatch.setattr(context_module, "MAX_CONTEXT_TRIGGERS", 2)
    profile = load_profile("hw5103-open-evidence")
    state = tmp_path / "state.json"
    store = EvidenceStateStore.open(state, profile)
    contexts = tmp_path / "contexts"
    manager = ContextCaptureManager(contexts, profile)
    for second in range(5):
        raw_time = f"2026-10-01 21:00:0{second}.000"
        timestamp = {"raw": raw_time, "utc": None, "display": None}
        store.observe_frame(timestamp, initiated_by_ebusd=False)
        manager.observe((raw_time + " <f108b50905540200ba080000080201ba0820000000\n").encode())
        event = {
            "check_id": "hmu_ba08_variants", "timestamp": timestamp,
            "source": "f1", "target": "08", "pbsb": "b509",
            "request": "05540200ba08", "response": "080201ba0820000000",
            "value_status": "decoded", "value": 32,
        }
        store.add(event)
        manager.trigger_event(event)
    manager.finish()
    first, second = tmp_path / "a.zip", tmp_path / "b.zip"
    for output in (first, second):
        create_bundle(output, profile, state_path=state, context_dir=contexts)
        result = verify_submission_bundle(output)
        assert result["submission_policy"]["valid"] is True
        assert result["context_metadata_count"] == 3
        assert result["context_raw_count"] == 0
    assert first.read_bytes() == second.read_bytes()

    with zipfile.ZipFile(first) as archive:
        members = {name: archive.read(name) for name in archive.namelist()}
    name = next(name for name in members if name.startswith("contexts/"))
    metadata = json.loads(members[name])
    metadata["continuation_of"] = "../private.raw"
    members[name] = json.dumps(metadata).encode()
    checksums = json.loads(members["checksums.json"])
    checksums["sha256"][name] = hashlib.sha256(members[name]).hexdigest()
    members["checksums.json"] = json.dumps(checksums).encode()
    with zipfile.ZipFile(second, "w") as archive:
        for name, content in members.items():
            archive.writestr(name, content)
    from ebus_evidence.bundle import BundleError
    with pytest.raises(BundleError, match="safe raw filename"):
        verify_bundle(second)


def _timestamp():
    return {
        "raw": "2026-10-01 21:00:00.000",
        "utc": "2026-10-01T21:00:00.000Z",
        "display": "2026-10-01T23:00:00.000+02:00",
    }


def _valid_submission(tmp_path):
    profile = load_profile("hw5103-open-evidence")
    state_path = tmp_path / "state.json"
    store = EvidenceStateStore.open(state_path, profile)
    store.observe_frame(_timestamp(), initiated_by_ebusd=False)

    output = tmp_path / "evidence.zip"
    create_bundle(output, profile, state_path=state_path)
    return output, profile


def test_submission_accepts_current_trusted_bundle(tmp_path):
    bundle, profile = _valid_submission(tmp_path)

    result = verify_submission_bundle(bundle)

    assert result["valid"] is True
    assert result["submission_policy"]["valid"] is True
    assert result["profile"] == profile["name"]
    assert result["profile_version"] == profile["version"]
    assert result["context_raw_count"] == 0
    assert result["deterministic_layout"] is True


def test_submission_rejects_modified_profile_with_trusted_name(tmp_path):
    trusted = load_profile("hw5103-open-evidence")
    modified = deepcopy(trusted)
    modified["checks"][0]["match"] = {
        **modified["checks"][0]["match"],
        "source": "00",
    }

    state_path = tmp_path / "state.json"
    store = EvidenceStateStore.open(state_path, modified)
    store.observe_frame(_timestamp(), initiated_by_ebusd=False)

    output = tmp_path / "modified-profile.zip"
    create_bundle(output, modified, state_path=state_path)

    assert verify_bundle(output)["valid"] is True
    with pytest.raises(SubmissionError, match="trusted bundled submission profile"):
        verify_submission_bundle(output)


def test_submission_rejects_untrusted_profile_before_generic_verifier(
    tmp_path, monkeypatch
):
    trusted = load_profile("hw5103-open-evidence")
    modified = deepcopy(trusted)
    modified["checks"][0]["match"] = {
        **modified["checks"][0]["match"],
        "target": "00",
    }

    state_path = tmp_path / "state.json"
    store = EvidenceStateStore.open(state_path, modified)
    store.observe_frame(_timestamp(), initiated_by_ebusd=False)
    output = tmp_path / "untrusted-profile.zip"
    create_bundle(output, modified, state_path=state_path)

    def should_not_run(_path):
        raise AssertionError("generic verifier must not parse untrusted profile first")

    monkeypatch.setattr(submission, "verify_bundle", should_not_run)

    with pytest.raises(SubmissionError, match="trusted bundled submission profile"):
        verify_submission_bundle(output)


def test_submission_rejects_raw_context_before_full_verification(tmp_path):
    output = tmp_path / "raw-context.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("contexts/example.raw", b"untrusted raw context")

    with pytest.raises(SubmissionError, match="raw context"):
        verify_submission_bundle(output)


def test_submission_rejects_non_deflate_before_generic_verifier(
    tmp_path, monkeypatch
):
    original, _ = _valid_submission(tmp_path)
    stored = tmp_path / "stored.zip"

    with zipfile.ZipFile(original) as src, zipfile.ZipFile(
        stored, "w", compression=zipfile.ZIP_STORED
    ) as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))

    def should_not_run(_path):
        raise AssertionError("generic verifier must not run before compression preflight")

    monkeypatch.setattr(submission, "verify_bundle", should_not_run)

    with pytest.raises(SubmissionError, match="DEFLATE-compressed"):
        verify_submission_bundle(stored)


def test_submission_rejects_repacked_nondeterministic_bundle(tmp_path):
    original, _ = _valid_submission(tmp_path)
    repacked = tmp_path / "repacked.zip"

    with zipfile.ZipFile(original) as src, zipfile.ZipFile(
        repacked, "w", compression=zipfile.ZIP_DEFLATED
    ) as dst:
        for name in src.namelist():
            dst.writestr(name, src.read(name))

    assert verify_bundle(repacked)["valid"] is True
    assert verify_bundle(repacked)["deterministic_layout"] is False
    with pytest.raises(SubmissionError, match="deterministic exporter layout"):
        verify_submission_bundle(repacked)


def test_submission_preflight_rejects_archive_size_before_verification(
    tmp_path, monkeypatch
):
    bundle, _ = _valid_submission(tmp_path)
    monkeypatch.setattr(
        submission,
        "MAX_SUBMISSION_ARCHIVE_BYTES",
        bundle.stat().st_size - 1,
    )

    with pytest.raises(SubmissionError, match="25 MB public upload policy"):
        verify_submission_bundle(bundle)


def test_submission_preflight_rejects_member_count_before_verification(
    tmp_path, monkeypatch
):
    bundle, _ = _valid_submission(tmp_path)
    monkeypatch.setattr(submission, "MAX_SUBMISSION_MEMBERS", 1)

    with pytest.raises(SubmissionError, match="too many ZIP members"):
        verify_submission_bundle(bundle)


def test_submission_cli_reports_policy_pass(tmp_path, capsys):
    bundle, _ = _valid_submission(tmp_path)

    assert main(["verify", "--submission", str(bundle)]) == 0
    out = capsys.readouterr().out

    assert "Status: VALID" in out
    assert "Submission policy: PASS" in out
