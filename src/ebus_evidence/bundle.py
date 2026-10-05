from __future__ import annotations

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path, PurePosixPath
from typing import Any

import yaml

from ebus_evidence import __version__
from ebus_evidence.context import ContextError, context_metadata_scope, validate_capture_metadata
from ebus_evidence.profiles.loader import ProfileError, validate_profile_data
from ebus_evidence.provenance import ProvenanceError, bundle_provenance
from ebus_evidence.state import load_state, profile_fingerprint
from ebus_evidence.structure import StructureLimitError, validate_structure_limits
from ebus_evidence.system_identity import (
    SystemIdentityError,
    load_system_document,
    validate_system_document,
)


_BUNDLE_FORMAT = "ebus-evidence-bundle-v1"
_SHARED_STATE_FORMAT = "ebus-evidence-shared-state-v1"
_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


class BundleError(ValueError):
    pass


def _validate_structure_limits(value: Any, *, label: str) -> None:
    try:
        validate_structure_limits(value, label=label)
    except StructureLimitError as exc:
        raise BundleError(str(exc)) from exc


def _canonical_json(data: Any) -> bytes:
    try:
        return (json.dumps(data, indent=2, sort_keys=True) + "\n").encode("utf-8")
    except (RecursionError, ValueError) as exc:
        raise BundleError(f"cannot serialize JSON structure: {exc}") from exc


def _canonical_yaml(data: Any) -> bytes:
    try:
        return yaml.safe_dump(
            data,
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        ).encode("utf-8")
    except (RecursionError, yaml.YAMLError) as exc:
        raise BundleError(f"cannot serialize YAML structure: {exc}") from exc


def _valid_sha256(value: Any) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(ch in "0123456789abcdef" for ch in value)
    )


def _validate_shared_observation(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BundleError("shared state observation must be a mapping")

    expected_keys = {
        "frames_seen",
        "passive_frames",
        "ebusd_initiated_frames",
        "non_frames",
        "skipped",
        "first_frame_timestamp",
        "last_frame_timestamp",
    }
    if set(value) != expected_keys:
        raise BundleError("shared state observation has unexpected fields")

    for key in (
        "frames_seen",
        "passive_frames",
        "ebusd_initiated_frames",
        "non_frames",
        "skipped",
    ):
        count = value.get(key)
        if not isinstance(count, int) or isinstance(count, bool) or count < 0:
            raise BundleError(
                f"shared state observation {key} must be a non-negative integer"
            )

    if value["passive_frames"] + value["ebusd_initiated_frames"] != value["frames_seen"]:
        raise BundleError(
            "shared state observation passive/initiated frame counts must sum to frames_seen"
        )

    normalized = deepcopy(value)
    for key in ("first_frame_timestamp", "last_frame_timestamp"):
        timestamp = value.get(key)
        if timestamp is None:
            continue
        if not isinstance(timestamp, dict) or set(timestamp) != {"raw", "utc", "display"}:
            raise BundleError(
                f"shared state observation {key} must contain raw/utc/display"
            )
        if not isinstance(timestamp.get("raw"), str) or not timestamp["raw"]:
            raise BundleError(
                f"shared state observation {key} requires a non-empty raw timestamp"
            )
        for optional in ("utc", "display"):
            if timestamp.get(optional) is not None and not isinstance(
                timestamp.get(optional), str
            ):
                raise BundleError(
                    f"shared state observation {key} {optional} must be a string or null"
                )

    if value["frames_seen"] == 0:
        if value["first_frame_timestamp"] is not None or value["last_frame_timestamp"] is not None:
            raise BundleError(
                "shared state observation timestamps must be null when frames_seen is zero"
            )
    else:
        if value["first_frame_timestamp"] is None or value["last_frame_timestamp"] is None:
            raise BundleError(
                "shared state observation timestamps are required when frames were seen"
            )

    return normalized


def _validate_shared_epoch(
    epoch: Any,
    *,
    profile_name: str,
    active_version: int,
    previous_version: int,
    index: int,
) -> int:
    label = f"shared state epoch {index}"
    if not isinstance(epoch, dict):
        raise BundleError(f"{label} must be a mapping")
    if epoch.get("profile") != profile_name:
        raise BundleError(f"{label} profile mismatch")

    version = epoch.get("profile_version")
    if (
        not isinstance(version, int)
        or isinstance(version, bool)
        or version < 1
        or version >= active_version
    ):
        raise BundleError(
            f"{label} profile_version must be a positive integer below active version"
        )
    if version <= previous_version:
        raise BundleError("shared state epoch versions must be strictly increasing")

    fingerprint = epoch.get("profile_fingerprint")
    if fingerprint is not None and not _valid_sha256(fingerprint):
        raise BundleError(f"{label} profile_fingerprint is invalid")

    for key in ("created_at", "updated_at", "ended_at"):
        value = epoch.get(key)
        if not isinstance(value, str) or not value:
            raise BundleError(f"{label} requires non-empty {key}")

    total_events = epoch.get("total_events")
    if (
        not isinstance(total_events, int)
        or isinstance(total_events, bool)
        or total_events < 0
    ):
        raise BundleError(f"{label} total_events must be a non-negative integer")

    _validate_shared_observation(epoch.get("observation"))
    if not isinstance(epoch.get("checks"), dict):
        raise BundleError(f"{label} checks must be a mapping")
    return version


def _safe_context_raw_name(value: Any) -> str:
    if not isinstance(value, str) or not value:
        raise BundleError("context raw_file must be a non-empty filename")
    pure = PurePosixPath(value)
    if (
        "/" in value
        or "\\" in value
        or pure.is_absolute()
        or ".." in pure.parts
        or pure.name != value
    ):
        raise BundleError(f"invalid context raw_file name: {value!r}")
    return value


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
        "profile_fingerprint": state.get("profile_fingerprint"),
        "created_at": state.get("created_at"),
        "updated_at": state.get("updated_at"),
        "total_events": int(state.get("total_events", 0)),
        "observation": deepcopy(state.get("observation")),
        "epochs": deepcopy(state.get("epochs", [])),
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
) -> tuple[list[tuple[str, bytes]], int]:
    if context_dir is None:
        return [], 0

    directory = Path(context_dir)
    if not directory.exists():
        raise BundleError(f"context directory not found: {directory}")
    if not directory.is_dir():
        raise BundleError(f"context path is not a directory: {directory}")
    try:
        scope = context_metadata_scope(directory, profile)
    except ContextError as exc:
        raise BundleError(str(exc)) from exc
    except RecursionError as exc:
        raise BundleError("context metadata structure is too deeply nested") from exc

    members: list[tuple[str, bytes]] = []
    for metadata_path in scope.current:
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BundleError(
                f"cannot read context metadata {metadata_path.name}: {exc}"
            ) from exc
        except RecursionError as exc:
            raise BundleError(
                f"context metadata {metadata_path.name} structure is too deeply nested"
            ) from exc
        _validate_structure_limits(
            metadata,
            label=f"context metadata {metadata_path.name}",
        )

        try:
            raw_name = _safe_context_raw_name(metadata.get("raw_file"))
        except BundleError as exc:
            raise BundleError(
                f"invalid raw_file in context metadata {metadata_path.name}: {exc}"
            ) from exc

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
                raise BundleError(
                    f"cannot read context raw file {raw_name}: {exc}"
                ) from exc
            members.append((f"contexts/{raw_name}", raw_bytes))

    return members, len(scope.historical)


def create_bundle(
    output: str | Path,
    profile: dict[str, Any],
    *,
    state_path: str | Path | None = None,
    context_dir: str | Path | None = None,
    system_path: str | Path | None = None,
    include_context_raw: bool = False,
) -> dict[str, Any]:
    _validate_structure_limits(profile, label="profile")
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
            state = load_state(
                state_file,
                profile,
                allow_profile_rollover=True,
            )
        except (OSError, ValueError) as exc:
            raise BundleError(f"cannot load evidence state: {exc}") from exc
        except RecursionError as exc:
            raise BundleError("cannot load evidence state: structure is too deeply nested") from exc
        _validate_structure_limits(state, label="evidence state")
        state_summary = shared_state(state)
        members.append(("evidence/state.json", _canonical_json(state_summary)))

    system_identity = None
    if system_path is not None:
        try:
            system_identity = load_system_document(system_path)
        except SystemIdentityError as exc:
            raise BundleError(f"cannot load system identity: {exc}") from exc
        except RecursionError as exc:
            raise BundleError("cannot load system identity: structure is too deeply nested") from exc
        _validate_structure_limits(system_identity, label="system identity")
        members.append(("system.json", _canonical_json(system_identity)))

    context_members, historical_context_metadata_count = _load_contexts(
        context_dir,
        profile,
        include_raw=include_context_raw,
    )
    members.extend(context_members)

    profile_bytes = _canonical_yaml(profile)
    members.append(("profile.yaml", profile_bytes))

    context_metadata_count = sum(
        1 for name, _ in context_members if name.endswith(".json")
    )
    context_raw_count = sum(
        1 for name, _ in context_members if name.endswith(".raw")
    )

    if state_summary is None and context_metadata_count == 0:
        raise BundleError("no evidence found in the requested bundle inputs")

    try:
        provenance = bundle_provenance(profile_bytes=profile_bytes)
    except ProvenanceError as exc:
        raise BundleError(f"cannot determine bundle provenance: {exc}") from exc

    manifest = {
        "format": _BUNDLE_FORMAT,
        "tool_version": __version__,
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "provenance": provenance,
        "evidence_state_included": state_summary is not None,
        "system_identity_included": system_identity is not None,
        "context_metadata_count": context_metadata_count,
        "context_raw_count": context_raw_count,
        "context_raw_included": context_raw_count > 0,
        "privacy": {
            "absolute_paths_included": False,
            "resume_checkpoint_included": False,
            "host_metadata_included": False,
            "credentials_included": False,
            "full_raw_log_included": False,
            "absolute_timestamps_included": True,
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
        "state_summary": state_summary,
        "system_identity": system_identity,
        "historical_context_metadata_excluded": historical_context_metadata_count,
        "sha256": hashlib.sha256(output_path.read_bytes()).hexdigest(),
    }



def _read_member(archive: zipfile.ZipFile, name: str) -> bytes:
    try:
        return archive.read(name)
    except KeyError as exc:
        raise BundleError(f"missing required bundle member: {name}") from exc
    except (OSError, RuntimeError, NotImplementedError, zipfile.BadZipFile) as exc:
        raise BundleError(f"cannot read bundle member {name}: {exc}") from exc


def _json_member(archive: zipfile.ZipFile, name: str) -> Any:
    try:
        decoded = _read_member(archive, name).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BundleError(f"invalid UTF-8 in {name}: {exc}") from exc
    try:
        value = json.loads(decoded)
    except json.JSONDecodeError as exc:
        raise BundleError(f"invalid JSON in {name}: {exc}") from exc
    except RecursionError as exc:
        raise BundleError(f"invalid JSON in {name}: structure is too deeply nested") from exc
    _validate_structure_limits(value, label=name)
    return value


def _forbidden_keys_present(value: Any, forbidden: set[str]) -> set[str]:
    found: set[str] = set()
    stack = [value]
    while stack:
        current = stack.pop()
        if isinstance(current, dict):
            for key, child in current.items():
                if key in forbidden:
                    found.add(key)
                stack.append(child)
        elif isinstance(current, list):
            stack.extend(current)
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

        allowed_fixed = required | {"evidence/state.json", "system.json"}
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
        except (UnicodeDecodeError, yaml.YAMLError) as exc:
            raise BundleError(f"invalid profile.yaml: {exc}") from exc
        except RecursionError as exc:
            raise BundleError("invalid profile.yaml: structure is too deeply nested") from exc
        _validate_structure_limits(profile_data, label="profile.yaml")
        try:
            profile = validate_profile_data(profile_data)
        except ProfileError as exc:
            raise BundleError(f"invalid profile.yaml: {exc}") from exc

        if manifest["profile"] != profile["name"]:
            raise BundleError("manifest/profile name mismatch")
        if manifest["profile_version"] != profile.get("version", 1):
            raise BundleError("manifest/profile version mismatch")

        provenance = manifest.get("provenance")
        if provenance is not None:
            if not isinstance(provenance, dict):
                raise BundleError("manifest provenance must be a mapping when present")

            tool_runtime = provenance.get("tool_runtime")
            if not isinstance(tool_runtime, dict):
                raise BundleError("manifest provenance requires tool_runtime")
            if tool_runtime.get("algorithm") != "ebus-evidence-runtime-sha256-v1":
                raise BundleError("unsupported tool runtime provenance algorithm")
            if not _valid_sha256(tool_runtime.get("sha256")):
                raise BundleError("manifest provenance tool runtime SHA-256 is invalid")

            profile_sha256 = provenance.get("profile_sha256")
            if not _valid_sha256(profile_sha256):
                raise BundleError("manifest provenance profile SHA-256 is invalid")
            if profile_sha256 != checksums["profile.yaml"]:
                raise BundleError(
                    "manifest provenance profile SHA-256 does not match profile.yaml"
                )

            git_provenance = provenance.get("git")
            if git_provenance is not None:
                if not isinstance(git_provenance, dict):
                    raise BundleError("manifest provenance git must be a mapping or null")
                commit = git_provenance.get("commit")
                if (
                    not isinstance(commit, str)
                    or len(commit) not in {40, 64}
                    or any(ch not in "0123456789abcdef" for ch in commit)
                ):
                    raise BundleError("manifest provenance git commit is invalid")
                if not isinstance(git_provenance.get("dirty"), bool):
                    raise BundleError("manifest provenance git dirty must be boolean")

        state_present = "evidence/state.json" in names
        if bool(manifest.get("evidence_state_included")) != state_present:
            raise BundleError("manifest evidence_state_included does not match ZIP contents")

        system_present = "system.json" in names
        if bool(manifest.get("system_identity_included")) != system_present:
            raise BundleError("manifest system_identity_included does not match ZIP contents")

        system_identity = None
        if system_present:
            try:
                system_identity = validate_system_document(
                    _json_member(archive, "system.json")
                )
            except SystemIdentityError as exc:
                raise BundleError(f"invalid system.json: {exc}") from exc

        state = None
        if state_present:
            state = _json_member(archive, "evidence/state.json")
            if not isinstance(state, dict) or state.get("format") != _SHARED_STATE_FORMAT:
                raise BundleError("unsupported shared evidence state format")
            if state.get("profile") != profile["name"]:
                raise BundleError("shared state/profile name mismatch")
            if state.get("profile_version") != profile.get("version", 1):
                raise BundleError("shared state/profile version mismatch")

            state_fingerprint = state.get("profile_fingerprint")
            if state_fingerprint is not None:
                if not _valid_sha256(state_fingerprint):
                    raise BundleError("shared state profile_fingerprint is invalid")
                if state_fingerprint != profile_fingerprint(profile):
                    raise BundleError(
                        "shared state profile_fingerprint does not match profile.yaml"
                    )

            epochs = state.get("epochs", [])
            if not isinstance(epochs, list):
                raise BundleError("shared state epochs must be a list")
            previous_epoch_version = 0
            for index, epoch in enumerate(epochs):
                previous_epoch_version = _validate_shared_epoch(
                    epoch,
                    profile_name=profile["name"],
                    active_version=profile.get("version", 1),
                    previous_version=previous_epoch_version,
                    index=index,
                )

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

            observation = state.get("observation")
            if observation is not None:
                _validate_shared_observation(observation)

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
            try:
                validate_capture_metadata(metadata)
            except ContextError as exc:
                raise BundleError(f"invalid context capture metadata in {name}: {exc}") from exc
            try:
                raw_name = _safe_context_raw_name(metadata.get("raw_file"))
            except BundleError as exc:
                raise BundleError(f"invalid context raw_file reference in {name}: {exc}") from exc
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
        # New bundle-v1 files explicitly disclose that evidence contains
        # absolute timestamps. Older bundle-v1 files predate this privacy flag,
        # so absence remains accepted for backward compatibility.
        absolute_timestamps = privacy.get("absolute_timestamps_included")
        if absolute_timestamps is not None and absolute_timestamps is not True:
            raise BundleError(
                "manifest absolute_timestamps_included must be true when present"
            )

        raw_present = bool(context_raw_names)
        if privacy.get("context_raw_may_contain_device_specific_bus_data") is not raw_present:
            raise BundleError("manifest raw-data privacy flag does not match ZIP contents")
        if privacy.get("review_context_raw_before_public_sharing") is not raw_present:
            raise BundleError("manifest raw-review privacy flag does not match ZIP contents")

        deterministic_layout = (
            names == sorted(names)
            and all(info.date_time == _ZIP_TIME for info in infos)
            and all(info.compress_type == zipfile.ZIP_DEFLATED for info in infos)
        )

    return {
        "path": bundle_path,
        "valid": True,
        "sha256": hashlib.sha256(bundle_path.read_bytes()).hexdigest(),
        "member_count": len(names),
        "tool_version": manifest["tool_version"],
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "provenance": deepcopy(provenance) if isinstance(provenance, dict) else None,
        "state_included": state_present,
        "historical_epoch_count": (
            len(state.get("epochs", []))
            if isinstance(state, dict) and isinstance(state.get("epochs", []), list)
            else 0
        ),
        "historical_frames": (
            sum(
                int(epoch["observation"]["frames_seen"])
                for epoch in state.get("epochs", [])
                if isinstance(epoch, dict)
                and isinstance(epoch.get("observation"), dict)
            )
            if isinstance(state, dict)
            else 0
        ),
        "observation": (
            deepcopy(state.get("observation"))
            if isinstance(state, dict) and isinstance(state.get("observation"), dict)
            else None
        ),
        "system_identity_included": system_present,
        "topology_signature_sha256": (
            system_identity["topology_signature_sha256"]
            if system_identity is not None
            else None
        ),
        "context_metadata_count": len(context_metadata_names),
        "context_raw_count": len(context_raw_names),
        "absolute_timestamps_included": absolute_timestamps,
        "deterministic_layout": deterministic_layout,
    }
