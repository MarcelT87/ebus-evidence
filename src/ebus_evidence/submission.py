from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path
from typing import Any

import yaml

from ebus_evidence.bundle import BundleError, verify_bundle
from ebus_evidence.profiles.loader import ProfileError, load_profile


MAX_SUBMISSION_ARCHIVE_BYTES = 25_000_000
MAX_SUBMISSION_UNCOMPRESSED_BYTES = 64 * 1024 * 1024
MAX_SUBMISSION_MEMBERS = 1000

_TRUSTED_SUBMISSION_PROFILES = ("hw5103-open-evidence",)
_MAX_PROFILE_MEMBER_BYTES = 256 * 1024
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


def _trusted_profiles() -> dict[str, tuple[str, int]]:
    trusted: dict[str, tuple[str, int]] = {}
    for name in _TRUSTED_SUBMISSION_PROFILES:
        try:
            profile = load_profile(name)
        except ProfileError as exc:
            raise SubmissionError(
                f"cannot load trusted bundled submission profile {name!r}: {exc}"
            ) from exc
        digest = hashlib.sha256(_canonical_profile_bytes(profile)).hexdigest()
        trusted[digest] = (profile["name"], profile.get("version", 1))
    return trusted


def _preflight_submission_zip(path: Path) -> tuple[str, int, str]:
    try:
        archive_size = path.stat().st_size
    except OSError as exc:
        raise SubmissionError(f"cannot stat submission bundle: {exc}") from exc

    if archive_size > MAX_SUBMISSION_ARCHIVE_BYTES:
        raise SubmissionError(
            "submission ZIP exceeds the 25 MB public upload policy"
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

        names = [info.filename for info in infos]
        if len(names) != len(set(names)):
            raise SubmissionError("submission ZIP contains duplicate member names")

        total_uncompressed = sum(info.file_size for info in infos)
        if total_uncompressed > MAX_SUBMISSION_UNCOMPRESSED_BYTES:
            raise SubmissionError(
                "submission uncompressed size exceeds 64 MiB policy"
            )

        info_by_name = {info.filename: info for info in infos}
        profile_info = info_by_name.get("profile.yaml")
        if profile_info is not None and profile_info.file_size > _MAX_PROFILE_MEMBER_BYTES:
            raise SubmissionError(
                "profile.yaml exceeds the public submission limit"
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

        if profile_info is None:
            # Let the structural verifier report the normal missing-member error.
            return "", 0, ""

        try:
            embedded_profile = archive.read("profile.yaml")
        except (OSError, RuntimeError, zipfile.BadZipFile) as exc:
            raise BundleError(f"cannot read bundle member profile.yaml: {exc}") from exc

        embedded_sha256 = hashlib.sha256(embedded_profile).hexdigest()
        trusted = _trusted_profiles()
        matched = trusted.get(embedded_sha256)
        if matched is None:
            raise SubmissionError(
                "embedded profile does not match a trusted bundled submission profile"
            )

        return matched[0], matched[1], embedded_sha256


def verify_submission_bundle(path: str | Path) -> dict[str, Any]:
    bundle_path = Path(path)
    if not bundle_path.is_file():
        raise BundleError(f"bundle not found: {bundle_path}")

    trusted_name, trusted_version, trusted_profile_sha256 = (
        _preflight_submission_zip(bundle_path)
    )
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
    if result["profile"] != trusted_name or result["profile_version"] != trusted_version:
        raise SubmissionError(
            "verified profile identity does not match the trusted preflight profile"
        )
    if provenance["profile_sha256"] != trusted_profile_sha256:
        raise SubmissionError(
            "embedded profile hash changed between preflight and verification"
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
