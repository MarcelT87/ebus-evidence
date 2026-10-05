from pathlib import Path
import tomllib

from ebus_evidence import __version__


def test_project_version_matches_runtime_version():
    root = Path(__file__).resolve().parents[1]
    project = tomllib.loads(
        (root / "pyproject.toml").read_text(encoding="utf-8")
    )

    assert project["project"]["version"] == __version__
