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
