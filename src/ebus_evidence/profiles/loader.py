from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml


class ProfileError(ValueError):
    pass


def load_profile(path: str | Path) -> dict[str, Any]:
    profile_path = Path(path)
    try:
        data = yaml.safe_load(profile_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise ProfileError(f"cannot read profile: {exc}") from exc

    if not isinstance(data, dict):
        raise ProfileError("profile root must be a mapping")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise ProfileError("profile requires a non-empty name")
    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        raise ProfileError("profile requires at least one check")

    seen: set[str] = set()
    for index, check in enumerate(checks):
        if not isinstance(check, dict):
            raise ProfileError(f"check {index} must be a mapping")
        check_id = check.get("id")
        if not isinstance(check_id, str) or not check_id:
            raise ProfileError(f"check {index} requires an id")
        if check_id in seen:
            raise ProfileError(f"duplicate check id: {check_id}")
        seen.add(check_id)
        if not isinstance(check.get("match"), dict):
            raise ProfileError(f"check {check_id} requires a match mapping")
        value = check.get("value")
        if value is not None and not isinstance(value, dict):
            raise ProfileError(f"check {check_id} value must be a mapping")

    return data
