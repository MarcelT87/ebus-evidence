from __future__ import annotations

from importlib import resources
from pathlib import Path
from typing import Any

import yaml


class ProfileError(ValueError):
    pass


def _read_profile_text(path_or_name: str | Path) -> str:
    path = Path(path_or_name)
    if path.is_file():
        try:
            return path.read_text(encoding="utf-8")
        except OSError as exc:
            raise ProfileError(f"cannot read profile: {exc}") from exc

    value = str(path_or_name)
    if "/" in value or "\\" in value or path.suffix in {".yaml", ".yml"}:
        raise ProfileError(f"cannot read profile: file not found: {value}")

    name = value.removesuffix(".yaml").removesuffix(".yml")
    bundled = resources.files("ebus_evidence").joinpath(
        "bundled_profiles", f"{name}.yaml"
    )
    try:
        if not bundled.is_file():
            raise ProfileError(f"unknown bundled profile: {value}")
        return bundled.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ProfileError(f"cannot read bundled profile {value}: {exc}") from exc


def load_profile(path_or_name: str | Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(_read_profile_text(path_or_name))
    except yaml.YAMLError as exc:
        raise ProfileError(f"cannot parse profile: {exc}") from exc

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
