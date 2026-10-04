import json
from pathlib import Path

import ebus_evidence.importer as importer_module

from ebus_evidence.bundle import verify_bundle
from ebus_evidence.cli import main
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.system_identity import build_system_document, parse_scan_result


def test_status_blocks_export_for_invalid_optional_system_file(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))
    assert main(["import", "--raw", str(raw)]) == 0
    system = tmp_path / "data" / "system.json"
    system.write_text("{}")
    capsys.readouterr()

    assert main(["status", "--raw", str(raw)]) == 0
    output = capsys.readouterr().out
    assert "System identity ..... invalid" in output
    assert "Ready to export ..... NO" in output
    assert "Correct the invalid system identity file" in output
    assert main(["export"]) == 2
    assert not (tmp_path / "data" / "evidence.zip").exists()

    system.write_text(json.dumps(build_system_document(parse_scan_result(
        "08;Vaillant;HMU00;0902;5103"
    ))))
    assert main(["status", "--raw", str(raw)]) == 0
    assert "Ready to export ..... YES" in capsys.readouterr().out
    assert main(["export"]) == 0


def _record(timestamp: str) -> bytes:
    return f"{timestamp} <1008b50702090000\n".encode("ascii")


def _matching_record(timestamp: str) -> bytes:
    return (
        f"{timestamp} "
        "<f108b50905540200ba080000080201ba0820000000\n"
    ).encode("ascii")


def _write_rollover_profiles(tmp_path):
    v2 = tmp_path / "rollover-v2.yaml"
    v3 = tmp_path / "rollover-v3.yaml"

    base_check = """
  - id: old_check
    description: Existing v2 check
    match:
      source: "f1"
      target: "08"
      pbsb: "b509"
      request: "05540200ba08"
    value:
      from: response
      type: u8
      offset: 5
    context:
      when:
        value_nonzero: true
      before_seconds: 0
      after_seconds: 0
"""

    v2.write_text(
        (
            "name: rollover-test\n"
            "version: 2\n"
            "checks:\n"
            + base_check
        ),
        encoding="utf-8",
    )
    v3.write_text(
        (
            "name: rollover-test\n"
            "version: 3\n"
            "checks:\n"
            + base_check
            + """
  - id: new_v3_check
    description: New v3-only check
    match:
      source: "f1"
      target: "08"
      pbsb: "b509"
      request: "05540200a80e"
    value:
      from: response
      type: float32le
      offset: 5
"""
        ),
        encoding="utf-8",
    )
    return v2, v3


def test_beginner_collect_resume_status_export_flow(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 10:00:00.000"))

    assert main(
        ["collect", "--raw", str(raw), "--seconds", "0"]
    ) == 0

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    assert state_path.is_file()
    assert context_dir.is_dir()

    with raw.open("ab") as handle:
        handle.write(_matching_record("2026-10-01 10:00:01.000"))

    assert main(
        ["collect", "--raw", str(raw), "--seconds", "0"]
    ) == 0

    profile = load_profile("hw5103-open-evidence")
    state = EvidenceStateStore.open(state_path, profile)
    assert state.state["observation"]["frames_seen"] == 1
    assert state.total_events == 1

    assert main(["status", "--raw", str(raw)]) == 0
    assert main(["export"]) == 0

    bundle = tmp_path / "data" / "evidence.zip"
    assert bundle.is_file()
    verified = verify_bundle(bundle)
    assert verified["valid"] is True
    assert verified["deterministic_layout"] is True
    assert verified["state_included"] is True
    assert verified["context_raw_count"] == 0


def test_beginner_profile_rollover_preserves_old_coverage_without_replay(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    profile_v2_path, profile_v3_path = _write_rollover_profiles(tmp_path)
    profile_v2 = load_profile(profile_v2_path)
    profile_v3 = load_profile(profile_v3_path)

    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 10:00:00.000"))

    # First run establishes a fresh-end checkpoint for v2.
    assert main(
        [
            "collect",
            "--raw",
            str(raw),
            "--profile",
            str(profile_v2_path),
            "--seconds",
            "0",
        ]
    ) == 0

    with raw.open("ab") as handle:
        handle.write(_matching_record("2026-10-01 10:00:01.000"))

    # v2 observes one frame/event and captures one v2 context.
    assert main(
        [
            "collect",
            "--raw",
            str(raw),
            "--profile",
            str(profile_v2_path),
            "--seconds",
            "0",
        ]
    ) == 0

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    before = EvidenceStateStore.open(state_path, profile_v2)
    before_checkpoint = before.checkpoint
    assert before.state["observation"]["frames_seen"] == 1
    assert before.state["checks"]["old_check"]["matches"] == 1
    old_contexts = list(context_dir.glob("*.json"))
    assert len(old_contexts) == 1
    old_context = json.loads(old_contexts[0].read_text(encoding="utf-8"))
    assert old_context["profile_version"] == 2

    # Reader paths do not mutate the state. They tell the beginner to collect
    # once so the writer can perform the profile rollover under its state lock.
    capsys.readouterr()
    assert main(
        [
            "status",
            "--raw",
            str(raw),
            "--profile",
            str(profile_v3_path),
        ]
    ) == 0
    status_out = capsys.readouterr().out
    assert "profile rollover pending (v2 -> v3)" in status_out
    assert "Rollover preview .... read-only" in status_out
    assert "Ready to export ..... YES" in status_out

    # Export can represent the rollover read-only, which keeps static-import-only
    # installations usable even before a writer persists the new epoch locally.
    assert main(["export", "--profile", str(profile_v3_path)]) == 0
    export_before_out = capsys.readouterr().out
    assert "Profile rollover .... v2 -> v3 (read-only preview)" in export_before_out
    assert "Local state ......... unchanged until collect/watch persists rollover" in export_before_out
    assert "Historical contexts . 1 (kept local; excluded)" in export_before_out
    assert "Historical epochs .... 1 (1 frames)" in export_before_out

    preview_verified = verify_bundle(tmp_path / "data" / "evidence.zip")
    assert preview_verified["valid"] is True
    assert preview_verified["profile_version"] == 3
    assert preview_verified["historical_epoch_count"] == 1
    assert preview_verified["historical_frames"] == 1
    assert preview_verified["observation"]["frames_seen"] == 0

    unchanged_local = json.loads(state_path.read_text(encoding="utf-8"))
    assert unchanged_local["profile_version"] == 2
    assert "epochs" not in unchanged_local or unchanged_local["epochs"] == []

    # No new raw bytes are appended here. Persisted rollover must not replay old data.
    assert main(
        [
            "collect",
            "--raw",
            str(raw),
            "--profile",
            str(profile_v3_path),
            "--seconds",
            "0",
        ]
    ) == 0
    rollover_out = capsys.readouterr().out
    assert "Profile rollover .... v2 -> v3" in rollover_out
    assert "new epoch starts at 0 frames" in rollover_out

    rolled = EvidenceStateStore.open(state_path, profile_v3)
    assert rolled.checkpoint == before_checkpoint
    assert rolled.state["observation"]["frames_seen"] == 0
    assert rolled.state["checks"]["old_check"]["matches"] == 0
    assert rolled.state["checks"]["new_v3_check"]["matches"] == 0
    assert rolled.historical_frames == 1
    assert len(rolled.historical_epochs) == 1

    epoch = rolled.historical_epochs[0]
    assert epoch["profile_version"] == 2
    assert epoch["observation"]["frames_seen"] == 1
    assert epoch["checks"]["old_check"]["matches"] == 1
    assert "new_v3_check" not in epoch["checks"]

    # The v2 context stays on disk but is not mislabeled/exported as v3.
    assert old_contexts[0].is_file()

    assert main(["export", "--profile", str(profile_v3_path)]) == 0
    export_after_out = capsys.readouterr().out
    assert "Historical contexts . 1 (kept local; excluded)" in export_after_out
    assert "Historical epochs .... 1 (1 frames)" in export_after_out

    verified = verify_bundle(tmp_path / "data" / "evidence.zip")
    assert verified["valid"] is True
    assert verified["profile_version"] == 3
    assert verified["historical_epoch_count"] == 1
    assert verified["historical_frames"] == 1
    assert verified["observation"]["frames_seen"] == 0
    assert verified["context_metadata_count"] == 0

    # Only new bytes after rollover count toward v3 coverage.
    with raw.open("ab") as handle:
        handle.write(_matching_record("2026-10-01 10:00:02.000"))

    assert main(
        [
            "collect",
            "--raw",
            str(raw),
            "--profile",
            str(profile_v3_path),
            "--seconds",
            "0",
        ]
    ) == 0

    after_new_data = EvidenceStateStore.open(state_path, profile_v3)
    assert after_new_data.state["observation"]["frames_seen"] == 1
    assert after_new_data.state["checks"]["old_check"]["matches"] == 1
    assert after_new_data.state["checks"]["new_v3_check"]["matches"] == 0
    assert after_new_data.historical_frames == 1


def test_status_is_not_ready_when_context_metadata_is_invalid(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied.raw"
    raw.write_bytes(
        _record("2026-10-01 10:00:00.000")
        + _matching_record("2026-10-01 10:00:01.000")
    )

    assert main(["import", "--raw", str(raw)]) == 0
    context_file = next((tmp_path / "data" / "contexts").glob("*.json"))
    context_file.write_text("{invalid", encoding="utf-8")

    capsys.readouterr()
    assert main(["status", "--raw", str(raw)]) == 0
    out = capsys.readouterr().out
    assert "Context metadata .... invalid" in out
    assert "Ready to export ..... NO" in out


def test_export_automatically_includes_valid_system_identity(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 10:00:00.000"))
    assert main(["collect", "--raw", str(raw), "--seconds", "0"]) == 0
    with raw.open("ab") as handle:
        handle.write(_matching_record("2026-10-01 10:00:01.000"))
    assert main(["collect", "--raw", str(raw), "--seconds", "0"]) == 0

    data = tmp_path / "data"
    devices = parse_scan_result("08;Vaillant;HMU00;0902;5103;ignored\n")
    system = build_system_document(
        devices,
        declared_manufacturer="Vaillant",
        declared_model="TEST-MODEL",
    )
    (data / "system.json").write_text(
        json.dumps(system, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    assert main(["export"]) == 0
    verified = verify_bundle(data / "evidence.zip")
    assert verified["system_identity_included"] is True
    assert verified["context_raw_count"] == 0


def test_export_reports_public_submission_pass(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied.raw"
    raw.write_bytes(
        _record("2026-10-01 10:00:00.000")
        + _matching_record("2026-10-01 10:00:01.000")
    )

    assert main(["import", "--raw", str(raw)]) == 0
    capsys.readouterr()
    assert main(["export"]) == 0
    out = capsys.readouterr().out
    assert "Public submission ... PASS" in out
    assert "Ready to share." in out


def test_export_keeps_valid_bundle_but_blocks_public_ready_with_raw_context(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied.raw"
    raw.write_bytes(
        _record("2026-10-01 10:00:00.000")
        + _matching_record("2026-10-01 10:00:01.000")
    )

    assert main(["import", "--raw", str(raw)]) == 0
    capsys.readouterr()
    assert main(["export", "--include-context-raw"]) == 0
    out = capsys.readouterr().out
    assert "Public submission ... NOT READY" in out
    assert "raw context is not accepted" in out
    assert "Ready to share." not in out
    assert (tmp_path / "data" / "evidence.zip").is_file()
    assert verify_bundle(tmp_path / "data" / "evidence.zip")["valid"] is True


def test_export_requires_collected_evidence(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    assert main(["export"]) == 2
    out = capsys.readouterr().out
    assert "./evidence collect" in out
    assert "./evidence import --raw FILE" in out
    assert not (tmp_path / "data" / "evidence.zip").exists()


def test_export_refuses_zero_frame_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 10:00:00.000"))

    assert main(["collect", "--raw", str(raw), "--seconds", "0"]) == 0
    assert (tmp_path / "data" / "evidence-state.json").is_file()

    assert main(["status", "--raw", str(raw)]) == 0
    capsys.readouterr()
    assert main(["export"]) == 2
    out = capsys.readouterr().out
    assert "./evidence collect" in out
    assert "./evidence import --raw FILE" in out
    assert not (tmp_path / "data" / "evidence.zip").exists()


def test_beginner_hints_use_local_launcher(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-01 10:00:00.000"))

    assert main(["collect", "--raw", str(raw), "--seconds", "0"]) == 0
    out = capsys.readouterr().out
    assert "Next:\n  ./evidence export" in out

    assert main(["status", "--raw", str(raw)]) == 0
    out = capsys.readouterr().out
    assert "Next:\n  ./evidence collect" in out


def test_static_import_builds_exportable_state_and_preserves_source(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    original = (
        _record("2026-10-01 10:00:00.000")
        + _matching_record("2026-10-01 10:00:01.000")
    )
    raw.write_bytes(original)

    assert main(["import", "--raw", str(raw)]) == 0
    assert raw.read_bytes() == original

    profile = load_profile("hw5103-open-evidence")
    state_path = tmp_path / "data" / "evidence-state.json"
    state = EvidenceStateStore.open(state_path, profile)
    assert state.state["observation"]["frames_seen"] == 2
    assert state.total_events == 1
    assert state.checkpoint is None

    assert main(["export"]) == 0
    verified = verify_bundle(tmp_path / "data" / "evidence.zip")
    assert verified["valid"] is True
    assert verified["state_included"] is True
    assert verified["observation"]["frames_seen"] == 2
    assert verified["context_raw_count"] == 0


def test_static_import_refuses_to_mix_with_existing_state(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    assert main(["import", "--raw", str(raw)]) == 0
    capsys.readouterr()

    state_path = tmp_path / "data" / "evidence-state.json"
    before = state_path.read_bytes()

    assert main(["import", "--raw", str(raw)]) == 2
    out = capsys.readouterr().out
    assert "existing evidence state found" in out
    assert "observation histories are not mixed" in out
    assert state_path.read_bytes() == before


def test_static_import_can_include_rotated_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    rotated = tmp_path / "ebusd.raw.old"
    rotated.write_bytes(_record("2026-10-01 09:59:59.000"))
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    assert main(
        ["import", "--raw", str(raw), "--include-rotated"]
    ) == 0

    profile = load_profile("hw5103-open-evidence")
    state = EvidenceStateStore.open(
        tmp_path / "data" / "evidence-state.json",
        profile,
    )
    observation = state.state["observation"]
    assert observation["frames_seen"] == 2
    assert observation["first_frame_timestamp"]["raw"] == "2026-10-01 09:59:59.000"
    assert observation["last_frame_timestamp"]["raw"] == "2026-10-01 10:00:01.000"


def test_static_import_aborts_if_source_changes_without_publishing_state(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "changing-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    fingerprints = iter(
        [
            (1, 2, 100, 10),
            (1, 2, 101, 11),
        ]
    )
    monkeypatch.setattr(
        importer_module,
        "_fingerprint",
        lambda _path: next(fingerprints),
    )

    assert main(["import", "--raw", str(raw)]) == 2
    out = capsys.readouterr().out
    assert "raw source changed during import" in out
    assert not (tmp_path / "data" / "evidence-state.json").exists()
    assert not (tmp_path / "data" / "contexts").exists()


def test_static_import_rolls_back_published_contexts_if_state_commit_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    original_replace = Path.replace
    context_published = False

    def fail_final_state_publish(self, target):
        nonlocal context_published
        target_path = Path(target)
        if target_path.resolve() == context_dir.resolve():
            context_published = True
        if self.name == "state.json" and target_path.resolve() == state_path.resolve():
            raise OSError("simulated final state publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_final_state_publish)

    assert main(["import", "--raw", str(raw)]) == 2
    out = capsys.readouterr().out
    assert context_published is True
    assert "simulated final state publish failure" in out
    assert not state_path.exists()
    assert not context_dir.exists()


def test_static_import_restores_preexisting_empty_context_dir_on_state_commit_failure(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    context_dir.mkdir(parents=True)
    original_replace = Path.replace
    context_published = False

    def fail_final_state_publish(self, target):
        nonlocal context_published
        target_path = Path(target)
        if target_path.resolve() == context_dir.resolve():
            context_published = True
        if self.name == "state.json" and target_path.resolve() == state_path.resolve():
            raise OSError("simulated final state publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_final_state_publish)

    assert main(["import", "--raw", str(raw)]) == 2
    out = capsys.readouterr().out
    assert context_published is True
    assert "simulated final state publish failure" in out
    assert not state_path.exists()
    assert context_dir.is_dir()
    assert list(context_dir.iterdir()) == []


def test_static_import_succeeds_with_preexisting_empty_context_dir(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    context_dir.mkdir(parents=True)

    assert main(["import", "--raw", str(raw)]) == 0
    assert state_path.is_file()
    assert context_dir.is_dir()
    assert list(context_dir.glob("*.json"))
    assert list(context_dir.glob("*.raw"))


def test_static_import_restores_empty_context_dir_if_context_publish_fails(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(_matching_record("2026-10-01 10:00:01.000"))

    state_path = tmp_path / "data" / "evidence-state.json"
    context_dir = tmp_path / "data" / "contexts"
    context_dir.mkdir(parents=True)
    original_replace = Path.replace

    def fail_context_publish(self, target):
        if Path(target).resolve() == context_dir.resolve():
            raise OSError("simulated context publish failure")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_context_publish)

    assert main(["import", "--raw", str(raw)]) == 2
    out = capsys.readouterr().out
    assert "simulated context publish failure" in out
    assert not state_path.exists()
    assert context_dir.is_dir()
    assert list(context_dir.iterdir()) == []


def test_static_import_reports_truncated_requests_as_non_frames(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied-ebusd.raw"
    raw.write_bytes(
        _record("2026-10-01 10:00:00.000")
        + b"2026-10-01 10:00:01.000 >3115b55503a400\n"
    )

    assert main(["import", "--raw", str(raw)]) == 0
    out = capsys.readouterr().out

    assert "Non-frames ............ 1" in out
    assert "Skipped ............... 0" in out
    assert "truncated_request" in out

    profile = load_profile("hw5103-open-evidence")
    state = EvidenceStateStore.open(
        tmp_path / "data" / "evidence-state.json",
        profile,
    )
    assert state.state["observation"]["frames_seen"] == 1
    assert state.state["observation"]["non_frames"] == 1
    assert state.state["observation"]["skipped"] == 0
