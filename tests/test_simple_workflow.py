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
    assert "hint: run './evidence collect' first" in out
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
    assert "run './evidence collect' while the raw log is growing" in out
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
