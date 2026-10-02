from __future__ import annotations

import zipfile
from copy import deepcopy

import pytest

import ebus_evidence.submission as submission
from ebus_evidence.bundle import create_bundle, verify_bundle
from ebus_evidence.cli import main
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.submission import SubmissionError, verify_submission_bundle


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
    with pytest.raises(SubmissionError, match="trusted bundled profile"):
        verify_submission_bundle(output)


def test_submission_rejects_raw_context_before_full_verification(tmp_path):
    output = tmp_path / "raw-context.zip"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("contexts/example.raw", b"untrusted raw context")

    with pytest.raises(SubmissionError, match="raw context"):
        verify_submission_bundle(output)


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

    with pytest.raises(SubmissionError, match="25 MiB public upload policy"):
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
