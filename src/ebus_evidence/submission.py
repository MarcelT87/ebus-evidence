from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

import yaml

from ebus_evidence.bundle import BundleError, verify_bundle
from ebus_evidence.profiles.loader import ProfileError, load_profile


MAX_SUBMISSION_ARCHIVE_BYTES = 25 * 1024 * 1024
MAX_SUBMISSION_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_SUBMISSION_MEMBERS = 1000

_MAX_SMALL_MEMBER_BYTES = 1024 * 1024
_MAX_STATE_MEMBER_BYTES = 32 * 1024 * 1024


class SubmissionError(ValueError):
    pass


def _canonical_profile_bytes(profile: dict[str, Any]) -> bytes:
    return yaml.safe_dump(
        profile,
        sort_keys=True,
        allow_unicode=True,
        default_flow_style=False,
    ).encode("utf-8")


def _preflight_submission_zip(path: Path) -> None:
    try:
        archive_size = path.stat().st_size
    except OSError as exc:
        raise SubmissionError(f"cannot stat submission bundle: {exc}") from exc

    if archive_size > MAX_SUBMISSION_ARCHIVE_BYTES:
        raise SubmissionError(
            "submission ZIP exceeds the 25 MiB public upload policy"
        )

    try:
        archive = zipfile.ZipFile(path)
    except (OSError, zipfile.BadZipFile) as exc:
        raise BundleError(f"cannot open bundle ZIP: {exc}") from exc

    with archive:
        infos = archive.infolist()
        if len(infos) > MAX_SUBMISSION_MEMBERS:
            raise SubmissionError(
                f"submission has too many ZIP members (>{MAX_SUBMISSION_MEMBERS})"
            )

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_SUBMISSION_UNCOMPRESSED_BYTES:
            raise SubmissionError(
                "submission uncompressed size exceeds 64 MiB policy"
            )

        for info in infos:
            if info.flag_bits & 0x1:
                raise SubmissionError(
                    f"encrypted ZIP members are not accepted: {info.filename}"
                )

            if info.filename.startswith("contexts/") and info.filename.endswith(".raw"):
                raise SubmissionError(
                    "raw context is not accepted in normal public submissions"
                )

            if info.filename == "evidence/state.json":
                if info.file_size > _MAX_STATE_MEMBER_BYTES:
                    raise SubmissionError(
                        "evidence/state.json exceeds the public submission limit"
                    )
            elif (
                info.filename in {
                    "manifest.json",
                    "profile.yaml",
                    "checksums.json",
                    "system.json",
                }
                or (
                    info.filename.startswith("contexts/")
                    and info.filename.endswith(".json")
                )
            ):
                if info.file_size > _MAX_SMALL_MEMBER_BYTES:
                    raise SubmissionError(
                        f"submission metadata member is unexpectedly large: "
                        f"{info.filename}"
                    )


def _trusted_profile_sha256(profile_name: str, profile_version: int) -> str:
    try:
        trusted = load_profile(profile_name)
    except ProfileError as exc:
        raise SubmissionError(
            f"profile is not an accepted bundled submission profile: "
            f"{profile_name!r}"
        ) from exc

    trusted_version = trusted.get("version", 1)
    if trusted_version != profile_version:
        raise SubmissionError(
            "submission profile version is not the currently bundled version: "
            f"submitted v{profile_version}, bundled v{trusted_version}"
        )

    return hashlib.sha256(_canonical_profile_bytes(trusted)).hexdigest()


def verify_submission_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    if not bundle_path.is_file():
        raise BundleError(f"bundle not found: {bundle_path}")

    _preflight_submission_zip(bundle_path)
    result = verify_bundle(bundle_path)

    if not result["state_included"]:
        raise SubmissionError(
            "public submissions require an evidence state"
        )

    if result["context_raw_count"] != 0:
        raise SubmissionError(
            "raw context is not accepted in normal public submissions"
        )

    if result["provenance"] is None:
        raise SubmissionError(
            "public submissions require current runtime/profile provenance"
        )

    if result["absolute_timestamps_included"] is not True:
        raise SubmissionError(
            "public submissions require explicit timestamp-disclosure metadata"
        )

    if not result["deterministic_layout"]:
        raise SubmissionError(
            "public submissions must use the deterministic exporter layout"
        )

    observation = result.get("observation")
    active_frames = (
        int(observation.get("frames_seen", 0))
        if isinstance(observation, dict)
        else 0
    )
    if (
        active_frames + int(result.get("historical_frames", 0)) == 0
        and int(result["context_metadata_count"]) == 0
    ):
        raise SubmissionError(
            "submission contains no observed evidence"
        )

    provenance = result["provenance"]
    trusted_profile_sha256 = _trusted_profile_sha256(
        result["profile"],
        result["profile_version"],
    )
    if provenance["profile_sha256"] != trusted_profile_sha256:
        raise SubmissionError(
            "embedded profile does not match the trusted bundled profile"
        )

    return {
        **result,
        "submission_policy": {
            "valid": True,
            "archive_size_limit_bytes": MAX_SUBMISSION_ARCHIVE_BYTES,
            "uncompressed_size_limit_bytes": MAX_SUBMISSION_UNCOMPRESSED_BYTES,
            "member_limit": MAX_SUBMISSION_MEMBERS,
            "trusted_profile_sha256": trusted_profile_sha256,
        },
    }
