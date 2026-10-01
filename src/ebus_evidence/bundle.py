from __future__ import annotations

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ebus_evidence import __version__
from ebus_evidence.profiles.loader import ProfileError, validate_profile_data
from ebus_evidence.state import load_state


_BUNDLE_FORMAT = "ebus-evidence-bundle-v1"
_SHARED_STATE_FORMAT = "ebus-evidence-shared-state-v1"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    pass


def _canonical_json(data: Any) -> bytes:
    return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _canonical_yaml(data: Any) -> bytes:
    return yaml.safe_dump(
        data,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).encode("utf-8")


def _zip_write(archive: zipfile.ZipFile, name: str, data: bytes) -> None:
    info = zipfile.ZipInfo(name, date_time=_ZIP_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.external_attr = 0o644 << 16
    archive.writestr(info, data)


def shared_state(state: dict[str, Any]) -> dict[str, Any]:
    """Return the shareable evidence subset, excluding local resume metadata."""
    return {
        "format": _SHARED_STATE_FORMAT,
        "profile": state["profile"],
        "profile_version": state["profile_version"],
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "total_events": int(state.get("total_events", 0)),
        "continuity_reset_count": len(
            state.get("continuity", {}).get("resets", [])
            if isinstance(state.get("continuity"), dict)
            else []
        ),
        "checks": deepcopy(state.get("checks", {})),
    }


def _load_contexts(
    context_dir: str | Path | None,
    profile: dict[str, Any],
    *,
    include_raw: bool,
) -> list[tuple[str, bytes]]:
    if context_dir is None:
        return []

    directory = Path(context_dir)
    if not directory.exists():
        raise BundleError(f"context directory not found: {directory}")
    if not directory.is_dir():
        raise BundleError(f"context path is not a directory: {directory}")

    members: list[tuple[str, bytes]] = []
    for metadata_path in sorted(directory.glob("*.json"), key=lambda p: p.name):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BundleError(f"cannot read context metadata {metadata_path.name}: {exc}") from exc

        if not isinstance(metadata, dict) or metadata.get("format") != "ebus-evidence-context-v1":
            raise BundleError(f"unsupported context metadata: {metadata_path.name}")
        if metadata.get("profile") != profile["name"]:
            raise BundleError(
                f"context profile mismatch in {metadata_path.name}: "
                f"{metadata.get('profile')!r} != {profile['name']!r}"
            )
        if metadata.get("profile_version") != profile.get("version", 1):
            raise BundleError(
                f"context profile version mismatch in {metadata_path.name}"
            )

        raw_name = metadata.get("raw_file")
        if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
            raise BundleError(f"invalid raw_file in context metadata: {metadata_path.name}")

        members.append(
            (f"contexts/{metadata_path.name}", _canonical_json(metadata))
        )

        if include_raw:
            raw_path = directory / raw_name
            if not raw_path.is_file():
                raise BundleError(
                    f"context raw file referenced by {metadata_path.name} is missing: {raw_name}"
                )
            try:
                raw_bytes = raw_path.read_bytes()
            except OSError as exc:
                raise BundleError(f"cannot read context raw file {raw_name}: {exc}") from exc
            members.append((f"contexts/{raw_name}", raw_bytes))

    return members


def create_bundle(
    output: str | Path,
    profile: dict[str, Any],
    *,
    state_path: str | Path | None = None,
    context_dir: str | Path | None = None,
    include_context_raw: bool = True,
) -> dict[str, Any]:
    if state_path is None and context_dir is None:
        raise BundleError("bundle requires --state, --context-dir, or both")

    output_path = Path(output)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    members: list[tuple[str, bytes]] = []
    state_summary = None

    if state_path is not None:
        state_file = Path(state_path)
        if not state_file.is_file():
            raise BundleError(f"evidence state not found: {state_file}")
        try:
            state = load_state(state_file, profile)
        except (OSError, ValueError) as exc:
            raise BundleError(f"cannot load evidence state: {exc}") from exc
        state_summary = shared_state(state)
        members.append(("evidence/state.json", _canonical_json(state_summary)))

    context_members = _load_contexts(
        context_dir,
        profile,
        include_raw=include_context_raw,
    )
    members.extend(context_members)

    members.append(("profile.yaml", _canonical_yaml(profile)))

    context_metadata_count = sum(
        1 for name, _ in context_members if name.endswith(".json")
    )
    context_raw_count = sum(
        1 for name, _ in context_members if name.endswith(".raw")
    )

    if state_summary is None and context_metadata_count == 0:
        raise BundleError("no evidence found in the requested bundle inputs")

    manifest = {
        "format": _BUNDLE_FORMAT,
        "tool_version": __version__,
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "evidence_state_included": state_summary is not None,
        "context_metadata_count": context_metadata_count,
        "context_raw_count": context_raw_count,
        "context_raw_included": context_raw_count > 0,
        "privacy": {
            "absolute_paths_included": False,
            "resume_checkpoint_included": False,
            "host_metadata_included": False,
            "credentials_included": False,
            "full_raw_log_included": False,
            "context_raw_may_contain_device_specific_bus_data": context_raw_count > 0,
            "review_context_raw_before_public_sharing": context_raw_count > 0,
        },
    }
    members.append(("manifest.json", _canonical_json(manifest)))

    members = sorted(members, key=lambda item: item[0])
    hashes = {
        name: hashlib.sha256(data).hexdigest()
        for name, data in members
        if name != "checksums.json"
    }
    members.append(("checksums.json", _canonical_json({"sha256": hashes})))
    members.sort(key=lambda item: item[0])

    temp_path = output_path.with_name(output_path.name + ".tmp")
    try:
        with zipfile.ZipFile(
            temp_path,
            mode="w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as archive:
            for name, data in members:
                _zip_write(archive, name, data)
        temp_path.replace(output_path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise BundleError(f"cannot write bundle: {exc}") from exc

    return {
        "path": output_path,
        "members": [name for name, _ in members],
        "manifest": manifest,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }



def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError as exc:
        raise BundleError(f"missing required bundle member: {name}") from exc
    except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
        raise BundleError(f"cannot read bundle member {name}: {exc}") from exc


def _json_member(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        return json.loads(_read_member(archive, name).decode("utf-8"))
    except UnicodeDecodeError as exc:
        raise BundleError(f"invalid UTF-8 in {name}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise BundleError(f"invalid JSON in {name}: {exc}") from exc


def _forbidden_keys_present(value: Any, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in forbidden:
                found.add(key)
            found.update(_forbidden_keys_present(child, forbidden))
    elif isinstance(value, list):
        for child in value:
            found.update(_forbidden_keys_present(child, forbidden))
    return found


def verify_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    if not bundle_path.is_file():
        raise BundleError(f"bundle not found: {bundle_path}")

    try:
        archive = zipfile.ZipFile(bundle_path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleError(f"cannot open bundle ZIP: {exc}") from exc

    with archive:
        infos = archive.infolist()
        if not infos:
            raise BundleError("bundle ZIP is empty")
        if len(infos) > 10000:
            raise BundleError("bundle has too many members")

        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise BundleError("bundle contains duplicate member names")

        total_size = sum(info.file_size for info in infos)
        if total_size > 512 * 1024 * 1024:
            raise BundleError("bundle uncompressed size exceeds 512 MiB")

        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if (
                not name
                or name.startswith("/")
                or "\\" in name
                or ".." in pure.parts
                or pure.is_absolute()
            ):
                raise BundleError(f"unsafe bundle member path: {name!r}")
            if info.is_dir():
                raise BundleError(f"unexpected directory member: {name}")

        required = {"manifest.json", "profile.yaml", "checksums.json"}
        missing = sorted(required - set(names))
        if missing:
            raise BundleError(f"missing required bundle members: {', '.join(missing)}")

        allowed_fixed = required | {"evidence/state.json"}
        for name in names:
            if name in allowed_fixed:
                continue
            if name.startswith("contexts/") and (
                name.endswith(".json") or name.endswith(".raw")
            ):
                continue
            raise BundleError(f"unexpected bundle member: {name}")

        checksums_doc = _json_member(archive, "checksums.json")
        if not isinstance(checksums_doc, dict) or not isinstance(
            checksums_doc.get("sha256"), dict
        ):
            raise BundleError("checksums.json requires a sha256 mapping")
        checksums = checksums_doc["sha256"]

        expected_checksum_names = set(names) - {"checksums.json"}
        if set(checksums) != expected_checksum_names:
            missing_hashes = sorted(expected_checksum_names - set(checksums))
            extra_hashes = sorted(set(checksums) - expected_checksum_names)
            details = []
            if missing_hashes:
                details.append("missing=" + ",".join(missing_hashes))
            if extra_hashes:
                details.append("extra=" + ",".join(extra_hashes))
            raise BundleError(
                "checksums.json member set mismatch"
                + (": " + "; ".join(details) if details else "")
            )

        for name in sorted(checksums):
            expected = checksums[name]
            if (
                not isinstance(expected, str)
                or len(expected) != 64
                or any(ch not in "0123456789abcdef" for ch in expected)
            ):
                raise BundleError(f"invalid SHA-256 digest for {name}")
            actual = hashlib.sha256(_read_member(archive, name)).hexdigest()
            if actual != expected:
                raise BundleError(f"checksum mismatch for {name}")

        manifest = _json_member(archive, "manifest.json")
        if not isinstance(manifest, dict) or manifest.get("format") != _BUNDLE_FORMAT:
            raise BundleError("unsupported bundle manifest format")
        if not isinstance(manifest.get("tool_version"), str):
            raise BundleError("manifest requires tool_version")
        if not isinstance(manifest.get("profile"), str) or not manifest["profile"]:
            raise BundleError("manifest requires profile")
        if not isinstance(manifest.get("profile_version"), int):
            raise BundleError("manifest requires integer profile_version")

        try:
            profile_data = yaml.safe_load(_read_member(archive, "profile.yaml").decode("utf-8"))
            profile = validate_profile_data(profile_data)
        except (UnicodeDecodeError, yaml.YAMLError, ProfileError) as exc:
            raise BundleError(f"invalid profile.yaml: {exc}") from exc

        if manifest["profile"] != profile["name"]:
            raise BundleError("manifest/profile name mismatch")
        if manifest["profile_version"] != profile.get("version", 1):
            raise BundleError("manifest/profile version mismatch")

        state_present = "evidence/state.json" in names
        if bool(manifest.get("evidence_state_included")) != state_present:
            raise BundleError("manifest evidence_state_included does not match ZIP contents")

        if state_present:
            state = _json_member(archive, "evidence/state.json")
            if not isinstance(state, dict) or state.get("format") != _SHARED_STATE_FORMAT:
                raise BundleError("unsupported shared evidence state format")
            if state.get("profile") != profile["name"]:
                raise BundleError("shared state/profile name mismatch")
            if state.get("profile_version") != profile.get("version", 1):
                raise BundleError("shared state/profile version mismatch")
            if not isinstance(state.get("total_events"), int) or state["total_events"] < 0:
                raise BundleError("shared state total_events must be a non-negative integer")
            if (
                not isinstance(state.get("continuity_reset_count"), int)
                or state["continuity_reset_count"] < 0
            ):
                raise BundleError(
                    "shared state continuity_reset_count must be a non-negative integer"
                )
            if not isinstance(state.get("checks"), dict):
                raise BundleError("shared state checks must be a mapping")

            expected_checks = {check["id"] for check in profile["checks"]}
            if set(state["checks"]) != expected_checks:
                raise BundleError("shared state check IDs do not match profile")

            forbidden = {
                "checkpoint",
                "device",
                "inode",
                "offset",
                "anchor_start",
                "anchor_sha256",
            }
            found = _forbidden_keys_present(state, forbidden)
            if found:
                raise BundleError(
                    "shared state contains forbidden local resume fields: "
                    + ", ".join(sorted(found))
                )

        context_metadata_names = sorted(
            name
            for name in names
            if name.startswith("contexts/") and name.endswith(".json")
        )
        context_raw_names = sorted(
            name
            for name in names
            if name.startswith("contexts/") and name.endswith(".raw")
        )

        if manifest.get("context_metadata_count") != len(context_metadata_names):
            raise BundleError("manifest context_metadata_count does not match ZIP contents")
        if manifest.get("context_raw_count") != len(context_raw_names):
            raise BundleError("manifest context_raw_count does not match ZIP contents")
        if bool(manifest.get("context_raw_included")) != bool(context_raw_names):
            raise BundleError("manifest context_raw_included does not match ZIP contents")

        referenced_raw: set[str] = set()
        for name in context_metadata_names:
            metadata = _json_member(archive, name)
            if (
                not isinstance(metadata, dict)
                or metadata.get("format") != "ebus-evidence-context-v1"
            ):
                raise BundleError(f"unsupported context metadata format: {name}")
            if metadata.get("profile") != profile["name"]:
                raise BundleError(f"context/profile name mismatch: {name}")
            if metadata.get("profile_version") != profile.get("version", 1):
                raise BundleError(f"context/profile version mismatch: {name}")
            raw_name = metadata.get("raw_file")
            if not isinstance(raw_name, str) or Path(raw_name).name != raw_name:
                raise BundleError(f"invalid context raw_file reference: {name}")
            referenced_raw.add(f"contexts/{raw_name}")

        unexpected_raw = set(context_raw_names) - referenced_raw
        if unexpected_raw:
            raise BundleError(
                "unreferenced context raw members: " + ", ".join(sorted(unexpected_raw))
            )
        if context_raw_names and referenced_raw != set(context_raw_names):
            missing_raw = sorted(referenced_raw - set(context_raw_names))
            raise BundleError(
                "context metadata references missing raw members: "
                + ", ".join(missing_raw)
            )

        privacy = manifest.get("privacy")
        if not isinstance(privacy, dict):
            raise BundleError("manifest requires privacy mapping")
        for key in (
            "absolute_paths_included",
            "resume_checkpoint_included",
            "host_metadata_included",
            "credentials_included",
            "full_raw_log_included",
        ):
            if privacy.get(key) is not False:
                raise BundleError(f"manifest privacy flag must be false: {key}")
        raw_present = bool(context_raw_names)
        if privacy.get("context_raw_may_contain_device_specific_bus_data") is not raw_present:
            raise BundleError("manifest raw-data privacy flag does not match ZIP contents")
        if privacy.get("review_context_raw_before_public_sharing") is not raw_present:
            raise BundleError("manifest raw-review privacy flag does not match ZIP contents")

        deterministic_layout = (
            names == sorted(names)
            and all(info.date_time == _ZIP_TIME for info in infos)
        )

    return {
        "path": bundle_path,
        "valid": True,
        "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "member_count": len(names),
        "tool_version": manifest["tool_version"],
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "state_included": state_present,
        "context_metadata_count": len(context_metadata_names),
        "context_raw_count": len(context_raw_names),
        "deterministic_layout": deterministic_layout,
    }
