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


def test_repository_profile_matches_bundled_profile():
    explicit = load_profile(ROOT / "profiles" / "hw5103-open-evidence.yaml")
    bundled = load_profile("hw5103-open-evidence")
    assert explicit == bundled


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


def test_profile_rejects_non_integer_version(tmp_path):
    path = tmp_path / "bad-version.yaml"
    path.write_text(
        """
name: bad-version
version: three
checks:
  - id: check
    match: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="positive integer"):
        load_profile(path)


def test_profile_rejects_zero_version(tmp_path):
    path = tmp_path / "zero-version.yaml"
    path.write_text(
        """
name: zero-version
version: 0
checks:
  - id: check
    match: {}
""".strip()
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="positive integer"):
        load_profile(path)


def test_profile_rejects_excessively_nested_local_structure(tmp_path):
    path = tmp_path / "deep.yaml"
    nested = '{"x":' * 80 + '0' + '}' * 80
    path.write_text(
        '{"name":"deep","version":1,"checks":[{"id":"check","match":{}}],'
        '"deep":' + nested + '}',
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="maximum nesting depth"):
        load_profile(path)


def test_profile_rejects_cyclic_yaml_alias_structure(tmp_path):
    path = tmp_path / "cyclic.yaml"
    path.write_text(
        "name: cyclic\n"
        "version: 1\n"
        "checks:\n"
        "  - id: check\n"
        "    match: {}\n"
        "cycle: &cycle\n"
        "  self: *cycle\n",
        encoding="utf-8",
    )

    with pytest.raises(ProfileError, match="repeated or cyclic container references"):
        load_profile(path)


def test_load_cross_hardware_profile_from_explicit_path():
    profile = load_profile(ROOT / "profiles" / "vaillant-cross-hardware-experimental.yaml")
    assert profile["name"] == "vaillant-cross-hardware-experimental"
    assert profile["version"] == 1
    assert {check["id"] for check in profile["checks"]} == {
        "b507_0209_reference",
        "b508_0209_state",
        "b505_025c00_periodic",
        "b510_020601_periodic",
        "b531_hmu_0301",
        "b531_vwz_0301",
        "b531_controller_0203",
        "b510_0b0017_companion",
    }


def test_load_cross_hardware_bundled_profile():
    profile = load_profile("vaillant-cross-hardware-experimental")
    assert profile["name"] == "vaillant-cross-hardware-experimental"
    assert profile["version"] == 1
