import json
from pathlib import Path

import ebus_evidence.importer as importer_module

from ebus_evidence.bundle import verify_bundle
from ebus_evidence.cli import main
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.system_identity import build_system_document, parse_scan_result


def _record(timestamp: str) -> bytes:
    return f"{timestamp} <1008b50702090000\n".encode("ascii")


def _matching_record(timestamp: str) -> bytes:
    return (
        f"{timestamp} "
        "<f108b50905540200ba080000080201ba0820000000\n"
    ).encode("ascii")


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
        if target_path == context_dir:
            context_published = True
        if self.name == "state.json" and target_path == state_path:
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
        if target_path == context_dir:
            context_published = True
        if self.name == "state.json" and target_path == state_path:
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
        if Path(target) == context_dir:
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
