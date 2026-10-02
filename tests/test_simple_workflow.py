import json

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
