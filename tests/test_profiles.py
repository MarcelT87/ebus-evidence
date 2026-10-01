from pathlib import Path

import pytest

from ebus_evidence.profiles.loader import ProfileError, load_profile


ROOT = Path(__file__).parents[1]


def test_load_profile_from_explicit_path():
    profile = load_profile(ROOT / "profiles" / "hw5103-open-evidence.yaml")
    assert profile["name"] == "hw5103-open-evidence"


def test_load_bundled_profile_by_name():
    profile = load_profile("hw5103-open-evidence")
    assert profile["name"] == "hw5103-open-evidence"
    assert profile["version"] == 2


def test_unknown_bundled_profile_is_rejected():
    with pytest.raises(ProfileError):
        load_profile("does-not-exist")


def test_bundled_profile_has_nonzero_context_triggers():
    profile = load_profile("hw5103-open-evidence")
    checks = {check["id"]: check for check in profile["checks"]}

    for check_id in ("hmu_a80e_nonzero", "hmu_ba08_variants"):
        context = checks[check_id]["context"]
        assert context["when"] == {"value_nonzero": True}
        assert context["before_seconds"] == 120
        assert context["after_seconds"] == 180

    assert "context" not in checks["vwzio_3538_variants"]
    assert "context" not in checks["vwzio_b512_states"]


def test_profile_rejects_invalid_context_condition(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        """
name: bad
version: 1
checks:
  - id: bad_check
    match: {}
    context:
      when:
        guessed_semantics: true
      before_seconds: 1
      after_seconds: 1
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="unsupported when keys"):
        load_profile(path)
