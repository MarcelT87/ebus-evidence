from __future__ import annotations

import os
from pathlib import Path
from typing import BinaryIO


class StateWriterLockError(RuntimeError):
    pass


def state_writer_lock_path(state_path: str | Path) -> Path:
    state = Path(state_path)
    return state.with_name(f".{state.name}.writer.lock")


class StateWriterLock:
    """Process-scoped advisory lock for one persistent evidence state.

    The small lock file is intentionally kept after release. Lock ownership is
    represented only by the operating-system file lock, so a leftover file is
    not evidence that another writer is still running.
    """

    def __init__(self, state_path: str | Path):
        self.state_path = Path(state_path)
        self.path = state_writer_lock_path(self.state_path)
        self._handle: BinaryIO | None = None

    def acquire(self) -> None:
        if self._handle is not None:
            raise StateWriterLockError(
                f"state writer lock is already held by this object: {self.state_path}"
            )

        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            handle = self.path.open("a+b")
            self._prepare_lock_byte(handle)
            self._lock_nonblocking(handle)
        except (OSError, StateWriterLockError) as exc:
            if "handle" in locals():
                handle.close()
            if isinstance(exc, StateWriterLockError):
                raise
            raise StateWriterLockError(
                f"cannot acquire state writer lock for {self.state_path}: {exc}"
            ) from exc

        self._handle = handle

    def release(self) -> None:
        handle = self._handle
        if handle is None:
            return
        self._handle = None
        try:
            self._unlock(handle)
        finally:
            handle.close()

    def __enter__(self) -> "StateWriterLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    @staticmethod
    def _prepare_lock_byte(handle: BinaryIO) -> None:
        # Windows byte-range locks need at least one byte. Keeping the same
        # byte on POSIX is harmless and makes the lock-file format portable.
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
            os.fsync(handle.fileno())
        handle.seek(0)

    def _lock_nonblocking(self, handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise StateWriterLockError(
                    "evidence state is already in use by another writer: "
                    f"{self.state_path}"
                ) from exc
            return

        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise StateWriterLockError(
                "evidence state is already in use by another writer: "
                f"{self.state_path}"
            ) from exc
        except OSError as exc:
            raise StateWriterLockError(
                f"cannot lock evidence state {self.state_path}: {exc}"
            ) from exc

    @staticmethod
    def _unlock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                # The descriptor is about to close. Do not mask the caller's
                # original exception with a best-effort unlock failure.
                pass
            return

        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
