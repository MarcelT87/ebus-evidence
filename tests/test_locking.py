import subprocess
import sys

import pytest

from ebus_evidence.cli import main
from ebus_evidence.locking import (
    StateWriterLock,
    StateWriterLockError,
    state_writer_lock_path,
)


def _record(timestamp: str) -> bytes:
    return f"{timestamp} <1008b50702090000\n".encode("ascii")


def _matching_record(timestamp: str) -> bytes:
    return (
        f"{timestamp} "
        "<f108b50905540200ba080000080201ba0820000000\n"
    ).encode("ascii")


def test_lock_path_is_hidden_next_to_state(tmp_path):
    state = tmp_path / "data" / "evidence-state.json"

    assert state_writer_lock_path(state) == (
        tmp_path / "data" / ".evidence-state.json.writer.lock"
    )


def test_second_writer_is_rejected_and_lock_can_be_reused(tmp_path):
    state = tmp_path / "state.json"
    first = StateWriterLock(state)
    second = StateWriterLock(state)

    first.acquire()
    try:
        with pytest.raises(StateWriterLockError, match="already in use"):
            second.acquire()
    finally:
        first.release()

    with StateWriterLock(state):
        assert state_writer_lock_path(state).is_file()


def test_different_state_paths_do_not_conflict(tmp_path):
    first_state = tmp_path / "one.json"
    second_state = tmp_path / "two.json"

    with StateWriterLock(first_state):
        with StateWriterLock(second_state):
            assert state_writer_lock_path(first_state).is_file()
            assert state_writer_lock_path(second_state).is_file()


def test_process_lock_is_released_after_hard_process_exit(tmp_path):
    state = tmp_path / "state.json"
    script = """
import sys
import time

from ebus_evidence.locking import StateWriterLock

lock = StateWriterLock(sys.argv[1])
lock.acquire()
print("LOCKED", flush=True)
time.sleep(30)
"""

    process = subprocess.Popen(
        [sys.executable, "-c", script, str(state)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "LOCKED"

        with pytest.raises(StateWriterLockError, match="already in use"):
            StateWriterLock(state).acquire()

        process.kill()
        process.wait(timeout=5)

        with StateWriterLock(state):
            assert state_writer_lock_path(state).is_file()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)


def test_collect_refuses_locked_state_before_writing(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-02 18:00:00.000"))
    state = tmp_path / "data" / "evidence-state.json"

    with StateWriterLock(state):
        assert main(
            [
                "collect",
                "--raw",
                str(raw),
                "--state",
                str(state),
                "--seconds",
                "0",
            ]
        ) == 2

    captured = capsys.readouterr()
    assert "already in use by another writer" in captured.err
    assert "leftover .writer.lock file is harmless" in captured.err
    assert not state.exists()

    assert main(
        [
            "collect",
            "--raw",
            str(raw),
            "--state",
            str(state),
            "--seconds",
            "0",
        ]
    ) == 0
    assert state.is_file()


def test_import_refuses_locked_state_before_publication(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "copied.raw"
    raw.write_bytes(
        _record("2026-10-02 18:00:00.000")
        + _matching_record("2026-10-02 18:00:01.000")
    )
    state = tmp_path / "data" / "import-state.json"
    contexts = tmp_path / "data" / "import-contexts"

    with StateWriterLock(state):
        assert main(
            [
                "import",
                "--raw",
                str(raw),
                "--state",
                str(state),
                "--context-dir",
                str(contexts),
            ]
        ) == 2

    captured = capsys.readouterr()
    assert "already in use by another writer" in captured.err
    assert not state.exists()
    assert not contexts.exists()


def test_watch_with_state_refuses_locked_state(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-02 18:00:00.000"))
    state = tmp_path / "watch-state.json"

    with StateWriterLock(state):
        assert main(
            [
                "watch",
                "--raw",
                str(raw),
                "--profile",
                "hw5103-open-evidence",
                "--state",
                str(state),
                "--seconds",
                "0",
            ]
        ) == 2

    captured = capsys.readouterr()
    assert "already in use by another writer" in captured.err
    assert not state.exists()


def test_watch_without_state_does_not_take_state_lock(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    raw = tmp_path / "ebusd.raw"
    raw.write_bytes(_record("2026-10-02 18:00:00.000"))

    assert main(
        [
            "watch",
            "--raw",
            str(raw),
            "--profile",
            "hw5103-open-evidence",
            "--seconds",
            "0",
        ]
    ) == 0
