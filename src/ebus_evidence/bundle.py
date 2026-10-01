from __future__ import annotations

import hashlib
import json
import zipfile
from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml

from ebus_evidence import __version__
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
        try:
            state = load_state(state_path, profile)
        except Exception as exc:
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

    manifest = {
        "format": _BUNDLE_FORMAT,
        "tool_version": __version__,
        "profile": profile["name"],
        "profile_version": profile.get("version", 1),
        "evidence_state_included": state_summary is not None,
        "context_metadata_count": context_metadata_count,
        "context_raw_count": context_raw_count,
        "context_raw_included": bool(include_context_raw),
        "privacy": {
            "absolute_paths_included": False,
            "resume_checkpoint_included": False,
            "host_metadata_included": False,
            "credentials_included": False,
            "full_raw_log_included": False,
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
