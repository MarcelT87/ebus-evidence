import hashlib
import shutil
import subprocess

from ebus_evidence.provenance import (
    bundle_provenance,
    git_source_provenance,
    tool_runtime_sha256,
)


def test_runtime_sha256_is_deterministic_and_ignores_non_runtime_files(tmp_path):
    package = tmp_path / "ebus_evidence"
    nested = package / "bundled_profiles"
    nested.mkdir(parents=True)
    (package / "__init__.py").write_text("__version__ = 'test'\n", encoding="utf-8")
    (nested / "profile.yaml").write_text("name: test\n", encoding="utf-8")
    (package / "README.txt").write_text("not runtime-hashed\n", encoding="utf-8")

    first = tool_runtime_sha256(package)
    second = tool_runtime_sha256(package)
    assert first == second
    assert len(first) == 64

    (package / "README.txt").write_text("changed but still ignored\n", encoding="utf-8")
    assert tool_runtime_sha256(package) == first

    (package / "__init__.py").write_text("__version__ = 'changed'\n", encoding="utf-8")
    assert tool_runtime_sha256(package) != first


def test_bundle_provenance_hashes_exact_profile_bytes(tmp_path):
    package = tmp_path / "ebus_evidence"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    profile_bytes = b"name: exact-profile\nversion: 3\n"

    provenance = bundle_provenance(
        profile_bytes=profile_bytes,
        package_root=package,
    )

    assert provenance["tool_runtime"]["algorithm"] == "ebus-evidence-runtime-sha256-v1"
    assert len(provenance["tool_runtime"]["sha256"]) == 64
    assert provenance["profile_sha256"] == hashlib.sha256(profile_bytes).hexdigest()
    assert provenance["git"] is None


def test_git_source_provenance_is_optional_outside_source_checkout(tmp_path):
    package = tmp_path / "site-packages" / "ebus_evidence"
    package.mkdir(parents=True)

    assert git_source_provenance(package) is None


def test_git_source_provenance_only_reports_exact_editable_source_checkout(tmp_path):
    repo = tmp_path / "repo"
    package = repo / "src" / "ebus_evidence"
    package.mkdir(parents=True)
    (repo / "pyproject.toml").write_text(
        '[project]\nname = "ebus-evidence"\nversion = "0.0.0"\n',
        encoding="utf-8",
    )
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    subprocess.run(["git", "init", str(repo)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(repo), "add", "."], check=True, capture_output=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(repo),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-m",
            "initial",
        ],
        check=True,
        capture_output=True,
    )

    clean = git_source_provenance(package)
    assert clean is not None
    assert len(clean["commit"]) in {40, 64}
    assert clean["dirty"] is False

    (package / "__init__.py").write_text("x = 2\n", encoding="utf-8")
    dirty = git_source_provenance(package)
    assert dirty is not None
    assert dirty["commit"] == clean["commit"]
    assert dirty["dirty"] is True

    installed = repo / ".venv" / "site-packages" / "ebus_evidence"
    shutil.copytree(package, installed)
    assert git_source_provenance(installed) is None
