from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any


_RUNTIME_HASH_ALGORITHM = "ebus-evidence-runtime-sha256-v1"
_RUNTIME_SUFFIXES = {".py", ".yaml", ".yml"}


class ProvenanceError(RuntimeError):
    pass


def _package_root() -> Path:
    return Path(__file__).resolve().parent


def tool_runtime_sha256(package_root: str | Path | None = None) -> str:
    """Hash the installed ebus_evidence runtime package deterministically."""
    root = Path(package_root) if package_root is not None else _package_root()
    root = root.resolve()

    digest = hashlib.sha256()
    digest.update((_RUNTIME_HASH_ALGORITHM + "\0").encode("ascii"))

    try:
        files = sorted(
            (
                path
                for path in root.rglob("*")
                if path.is_file() and path.suffix.lower() in _RUNTIME_SUFFIXES
            ),
            key=lambda path: path.relative_to(root).as_posix(),
        )

        for path in files:
            relative = path.relative_to(root).as_posix().encode("utf-8")
            data = path.read_bytes()
            digest.update(relative)
            digest.update(b"\0")
            digest.update(str(len(data)).encode("ascii"))
            digest.update(b"\0")
            digest.update(data)
            digest.update(b"\0")
    except OSError as exc:
        raise ProvenanceError(f"cannot fingerprint runtime package: {exc}") from exc

    return digest.hexdigest()


def _looks_like_source_checkout(root: Path) -> bool:
    pyproject = root / "pyproject.toml"
    package = root / "src" / "ebus_evidence"
    if not pyproject.is_file() or not package.is_dir():
        return False
    try:
        text = pyproject.read_text(encoding="utf-8")
    except OSError:
        return False
    return 'name = "ebus-evidence"' in text


def git_source_provenance(package_root: str | Path | None = None) -> dict[str, Any] | None:
    """Return source-checkout Git provenance when the runtime is inside that checkout."""
    root = Path(package_root) if package_root is not None else _package_root()
    root = root.resolve()

    try:
        repo_result = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "--show-toplevel"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        repo_root = Path(repo_result.stdout.strip()).resolve()
        if not _looks_like_source_checkout(repo_root):
            return None

        commit_result = subprocess.run(
            ["git", "-C", str(repo_root), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
        commit = commit_result.stdout.strip().lower()

        status_result = subprocess.run(
            ["git", "-C", str(repo_root), "status", "--porcelain=v1", "--untracked-files=all"],
            check=True,
            capture_output=True,
            text=True,
            timeout=2,
        )
    except (OSError, subprocess.SubprocessError):
        return None

    if len(commit) not in {40, 64} or any(ch not in "0123456789abcdef" for ch in commit):
        return None

    return {
        "commit": commit,
        "dirty": bool(status_result.stdout.strip()),
    }


def bundle_provenance(
    *,
    profile_bytes: bytes,
    package_root: str | Path | None = None,
) -> dict[str, Any]:
    return {
        "tool_runtime": {
            "algorithm": _RUNTIME_HASH_ALGORITHM,
            "sha256": tool_runtime_sha256(package_root),
        },
        "profile_sha256": hashlib.sha256(profile_bytes).hexdigest(),
        "git": git_source_provenance(package_root),
    }
