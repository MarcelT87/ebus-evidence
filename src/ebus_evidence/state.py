from __future__ import annotations

import hashlib
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ebus_evidence.structure import StructureLimitError, validate_structure_limits


_STATE_FORMAT = "ebus-evidence-state-v1"


class StateError(ValueError):
    pass


class ProfileRolloverRequired(StateError):
    def __init__(self, current_version: int, requested_version: int):
        self.current_version = current_version
        self.requested_version = requested_version
        super().__init__(
            "state profile rollover required: "
            f"v{current_version} -> v{requested_version}"
        )


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _profile_version(profile: dict[str, Any]) -> int:
    value = profile.get("version", 1)
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise StateError("profile version must be a positive integer")
    return value


def profile_fingerprint(profile: dict[str, Any]) -> str:
    """Fingerprint profile behavior while ignoring presentation-only descriptions."""
    semantic = deepcopy(profile)
    semantic["version"] = _profile_version(profile)
    semantic.pop("description", None)
    checks = semantic.get("checks", [])
    if isinstance(checks, list):
        normalized_checks = []
        for check in checks:
            item = deepcopy(check)
            if isinstance(item, dict):
                item.pop("description", None)
            normalized_checks.append(item)
        semantic["checks"] = sorted(
            normalized_checks,
            key=lambda item: str(item.get("id", "")) if isinstance(item, dict) else "",
        )
    payload = json.dumps(
        semantic,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _new_observation() -> dict[str, Any]:
    return {
        "frames_seen": 0,
        "passive_frames": 0,
        "ebusd_initiated_frames": 0,
        "non_frames": 0,
        "skipped": 0,
        "first_frame_timestamp": None,
        "last_frame_timestamp": None,
    }


def _new_check(check: dict[str, Any]) -> dict[str, Any]:
    return {
        "description": check.get("description", check["id"]),
        "matches": 0,
        "first_seen": None,
        "last_seen": None,
        "responses": {},
        "values": {},
        "value_status": {
            "decoded": 0,
            "no_response": 0,
            "decode_error": 0,
            "not_configured": 0,
        },
    }


def new_state(profile: dict[str, Any]) -> dict[str, Any]:
    now = _utc_now()
    return {
        "format": _STATE_FORMAT,
        "profile": profile["name"],
        "profile_version": _profile_version(profile),
        "profile_fingerprint": profile_fingerprint(profile),
        "created_at": now,
        "updated_at": now,
        "total_events": 0,
        "observation": _new_observation(),
        "epochs": [],
        "checkpoint": None,
        "continuity": {
            "resets": [],
        },
        "checks": {
            check["id"]: _new_check(check)
            for check in profile["checks"]
        },
    }


def _validate_sha256_or_none(value: Any, *, label: str) -> None:
    if value is None:
        return
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(ch not in "0123456789abcdef" for ch in value)
    ):
        raise StateError(f"{label} must be a lowercase SHA-256 hex digest or null")


def _validate_observation(observation: Any, *, label: str) -> None:
    if not isinstance(observation, dict):
        raise StateError(f"{label} must be a mapping")
    for key in (
        "frames_seen",
        "passive_frames",
        "ebusd_initiated_frames",
        "non_frames",
        "skipped",
    ):
        value = observation.get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise StateError(f"{label} {key} must be a non-negative integer")
    if (
        observation["passive_frames"] + observation["ebusd_initiated_frames"]
        != observation["frames_seen"]
    ):
        raise StateError(
            f"{label} passive/initiated frame counts must sum to frames_seen"
        )
    for key in ("first_frame_timestamp", "last_frame_timestamp"):
        value = observation.get(key)
        if value is not None and not isinstance(value, dict):
            raise StateError(f"{label} {key} must be a mapping or null")


def _validate_epochs(
    epochs: Any,
    *,
    profile_name: str,
    active_version: int,
) -> None:
    if not isinstance(epochs, list):
        raise StateError("state epochs must be a list")

    previous_version = 0
    for index, epoch in enumerate(epochs):
        label = f"state epoch {index}"
        if not isinstance(epoch, dict):
            raise StateError(f"{label} must be a mapping")
        if epoch.get("profile") != profile_name:
            raise StateError(f"{label} profile mismatch")
        version = epoch.get("profile_version")
        if (
            not isinstance(version, int)
            or isinstance(version, bool)
            or version < 1
            or version >= active_version
        ):
            raise StateError(
                f"{label} profile_version must be a positive integer below active version"
            )
        if version <= previous_version:
            raise StateError("state epoch profile versions must be strictly increasing")
        previous_version = version

        _validate_sha256_or_none(
            epoch.get("profile_fingerprint"),
            label=f"{label} profile_fingerprint",
        )
        for key in ("created_at", "updated_at", "ended_at"):
            value = epoch.get(key)
            if not isinstance(value, str) or not value:
                raise StateError(f"{label} requires non-empty {key}")
        total_events = epoch.get("total_events")
        if (
            not isinstance(total_events, int)
            or isinstance(total_events, bool)
            or total_events < 0
        ):
            raise StateError(f"{label} total_events must be a non-negative integer")
        _validate_observation(epoch.get("observation"), label=f"{label} observation")
        if not isinstance(epoch.get("checks"), dict):
            raise StateError(f"{label} checks must be a mapping")


def _validate_state_shape(state: dict[str, Any]) -> None:
    if state.get("format") != _STATE_FORMAT:
        raise StateError("unsupported state format")
    if not isinstance(state.get("profile"), str) or not state["profile"]:
        raise StateError("state profile must be a non-empty string")
    version = state.get("profile_version")
    if not isinstance(version, int) or isinstance(version, bool) or version < 1:
        raise StateError("state profile_version must be a positive integer")
    _validate_sha256_or_none(
        state.get("profile_fingerprint"),
        label="state profile_fingerprint",
    )
    if not isinstance(state.get("checks"), dict):
        raise StateError("state checks must be a mapping")
    for key in ("created_at", "updated_at"):
        value = state.get(key)
        if not isinstance(value, str) or not value:
            raise StateError(f"state requires non-empty {key}")

    total_events = state.get("total_events")
    if (
        not isinstance(total_events, int)
        or isinstance(total_events, bool)
        or total_events < 0
    ):
        raise StateError("state total_events must be a non-negative integer")

    _validate_observation(state.get("observation"), label="state observation")
    _validate_epochs(
        state.get("epochs"),
        profile_name=state["profile"],
        active_version=version,
    )

    checkpoint = state.get("checkpoint")
    if checkpoint is not None:
        if not isinstance(checkpoint, dict):
            raise StateError("state checkpoint must be a mapping or null")
        for key in ("device", "inode", "offset"):
            if not isinstance(checkpoint.get(key), int) or checkpoint[key] < 0:
                raise StateError(f"state checkpoint requires non-negative integer {key}")

        anchor_start = checkpoint.get("anchor_start")
        anchor_sha256 = checkpoint.get("anchor_sha256")
        if anchor_start is not None or anchor_sha256 is not None:
            if not isinstance(anchor_start, int) or not 0 <= anchor_start <= checkpoint["offset"]:
                raise StateError(
                    "state checkpoint anchor_start must be an integer within the checkpoint"
                )
            if (
                not isinstance(anchor_sha256, str)
                or len(anchor_sha256) != 64
                or any(ch not in "0123456789abcdef" for ch in anchor_sha256)
            ):
                raise StateError(
                    "state checkpoint anchor_sha256 must be a lowercase SHA-256 hex digest"
                )

    continuity = state.get("continuity")
    if not isinstance(continuity, dict):
        raise StateError("state continuity must be a mapping")
    resets = continuity.get("resets")
    if not isinstance(resets, list):
        raise StateError("state continuity resets must be a list")


def _validate_active_profile(state: dict[str, Any], profile: dict[str, Any]) -> None:
    if state.get("profile") != profile["name"]:
        raise StateError(
            f"state profile mismatch: {state.get('profile')!r} != {profile['name']!r}"
        )

    expected_version = _profile_version(profile)
    if state.get("profile_version") != expected_version:
        raise StateError(
            "state profile version mismatch: "
            f"{state.get('profile_version')!r} != {expected_version!r}"
        )

    expected_checks = {check["id"] for check in profile["checks"]}
    actual_checks = set(state["checks"])
    if actual_checks != expected_checks:
        raise StateError(
            "state check set differs from the profile without a version bump"
        )

    expected_fingerprint = profile_fingerprint(profile)
    current_fingerprint = state.get("profile_fingerprint")
    if current_fingerprint is None:
        state["profile_fingerprint"] = expected_fingerprint
    elif current_fingerprint != expected_fingerprint:
        raise StateError(
            "state profile semantics changed without a profile version bump"
        )


def _archive_active_epoch(state: dict[str, Any], *, ended_at: str) -> dict[str, Any]:
    return {
        "profile": state["profile"],
        "profile_version": state["profile_version"],
        "profile_fingerprint": state.get("profile_fingerprint"),
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "ended_at": ended_at,
        "total_events": int(state.get("total_events", 0)),
        "observation": deepcopy(state["observation"]),
        "checks": deepcopy(state["checks"]),
    }


def _rollover_state(
    state: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    # The rollover boundary is the last persisted update of the completed
    # observation, not the wall clock at which a newer tool happens to read it.
    # This makes read-only rollover previews deterministic and accurately ties
    # the historical epoch to the evidence state that was actually observed.
    ended_at = str(state["updated_at"])
    archived = _archive_active_epoch(state, ended_at=ended_at)
    replacement = new_state(profile)
    replacement["created_at"] = ended_at
    replacement["updated_at"] = ended_at
    replacement["epochs"] = deepcopy(state.get("epochs", [])) + [archived]
    replacement["checkpoint"] = deepcopy(state.get("checkpoint"))
    replacement["continuity"] = deepcopy(
        state.get("continuity", {"resets": []})
    )
    return replacement


def _load_state(
    path: str | Path,
    profile: dict[str, Any],
    *,
    allow_profile_rollover: bool,
) -> tuple[dict[str, Any], int | None]:
    state_path = Path(path)
    if not state_path.exists():
        return new_state(profile), None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state: {exc}") from exc
    except RecursionError as exc:
        raise StateError("cannot read state: structure is too deeply nested") from exc
    try:
        validate_structure_limits(data, label="state")
    except StructureLimitError as exc:
        raise StateError(str(exc)) from exc
    if not isinstance(data, dict):
        raise StateError("state root must be a mapping")

    # Backward-compatible additions to state-v1.
    data.setdefault("checkpoint", None)
    data.setdefault("observation", _new_observation())
    data.setdefault("continuity", {"resets": []})
    data.setdefault("epochs", [])
    data.setdefault("profile_fingerprint", None)
    if not isinstance(data["continuity"], dict):
        raise StateError("state continuity must be a mapping")
    data["continuity"].setdefault("resets", [])

    _validate_state_shape(data)

    if data.get("profile") != profile["name"]:
        raise StateError(
            f"state profile mismatch: {data.get('profile')!r} != {profile['name']!r}"
        )

    stored_version = int(data["profile_version"])
    requested_version = _profile_version(profile)

    if stored_version == requested_version:
        _validate_active_profile(data, profile)
        return data, None

    if requested_version < stored_version:
        raise StateError(
            "state profile downgrade is not supported: "
            f"v{stored_version} -> v{requested_version}"
        )

    if not allow_profile_rollover:
        raise ProfileRolloverRequired(stored_version, requested_version)

    rolled = _rollover_state(data, profile)
    _validate_state_shape(rolled)
    _validate_active_profile(rolled, profile)
    return rolled, stored_version


def load_state(
    path: str | Path,
    profile: dict[str, Any],
    *,
    allow_profile_rollover: bool = False,
) -> dict[str, Any]:
    state, _ = _load_state(
        path,
        profile,
        allow_profile_rollover=allow_profile_rollover,
    )
    return state


def update_observation_frame(
    state: dict[str, Any],
    timestamp: dict[str, Any],
    *,
    initiated_by_ebusd: bool,
) -> None:
    observation = state["observation"]
    copied_timestamp = deepcopy(timestamp)
    observation["frames_seen"] += 1
    if initiated_by_ebusd:
        observation["ebusd_initiated_frames"] += 1
    else:
        observation["passive_frames"] += 1
    observation["first_frame_timestamp"] = (
        observation["first_frame_timestamp"] or copied_timestamp
    )
    observation["last_frame_timestamp"] = copied_timestamp
    state["updated_at"] = _utc_now()


def update_observation_non_frame(state: dict[str, Any]) -> None:
    state["observation"]["non_frames"] += 1
    state["updated_at"] = _utc_now()


def update_observation_skip(state: dict[str, Any]) -> None:
    state["observation"]["skipped"] += 1
    state["updated_at"] = _utc_now()


def update_state(state: dict[str, Any], event: dict[str, Any]) -> None:
    check_id = str(event["check_id"])
    check = state["checks"].get(check_id)
    if check is None:
        raise StateError(f"event check is not present in state: {check_id}")

    timestamp = deepcopy(event["timestamp"])
    check["matches"] += 1
    check["first_seen"] = check["first_seen"] or timestamp
    check["last_seen"] = timestamp

    response = event.get("response") or "<none>"
    responses = check["responses"]
    item = responses.setdefault(
        response,
        {
            "count": 0,
            "first_seen": timestamp,
            "last_seen": timestamp,
        },
    )
    item["count"] += 1
    item["last_seen"] = timestamp

    status = str(event.get("value_status", "not_configured"))
    value_status = check["value_status"]
    value_status[status] = int(value_status.get(status, 0)) + 1

    if status == "decoded":
        value_key = json.dumps(event.get("value"), sort_keys=True, separators=(",", ":"))
        values = check["values"]
        value_item = values.setdefault(
            value_key,
            {
                "value": event.get("value"),
                "count": 0,
                "first_seen": timestamp,
                "last_seen": timestamp,
            },
        )
        value_item["count"] += 1
        value_item["last_seen"] = timestamp

    state["total_events"] += 1
    state["updated_at"] = _utc_now()


def save_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = state_path.with_name(state_path.name + ".tmp")
    payload = json.dumps(state, indent=2, sort_keys=True) + "\n"
    try:
        temp_path.write_text(payload, encoding="utf-8")
        with temp_path.open("rb") as handle:
            os.fsync(handle.fileno())
        os.replace(temp_path, state_path)
    except OSError as exc:
        try:
            temp_path.unlink(missing_ok=True)
        except OSError:
            pass
        raise StateError(f"cannot write state: {exc}") from exc


@dataclass(slots=True)
class EvidenceStateStore:
    path: Path
    profile: dict[str, Any]
    state: dict[str, Any]
    rolled_over_from: int | None = None

    @classmethod
    def open(
        cls,
        path: str | Path,
        profile: dict[str, Any],
        *,
        allow_profile_rollover: bool = False,
    ) -> "EvidenceStateStore":
        state_path = Path(path)
        state, rolled_over_from = _load_state(
            state_path,
            profile,
            allow_profile_rollover=allow_profile_rollover,
        )
        store = cls(
            path=state_path,
            profile=profile,
            state=state,
            rolled_over_from=rolled_over_from,
        )
        if rolled_over_from is not None:
            store.save()
        return store

    def save(self) -> None:
        save_state(self.path, self.state)

    def add(self, event: dict[str, Any], *, save: bool = True) -> None:
        update_state(self.state, event)
        if save:
            self.save()

    def observe_frame(
        self,
        timestamp: dict[str, Any],
        *,
        initiated_by_ebusd: bool,
        save: bool = True,
    ) -> None:
        update_observation_frame(
            self.state,
            timestamp,
            initiated_by_ebusd=initiated_by_ebusd,
        )
        if save:
            self.save()

    def observe_non_frame(self, *, save: bool = True) -> None:
        update_observation_non_frame(self.state)
        if save:
            self.save()

    def observe_skip(self, *, save: bool = True) -> None:
        update_observation_skip(self.state)
        if save:
            self.save()

    @property
    def checkpoint(self) -> dict[str, Any] | None:
        value = self.state.get("checkpoint")
        return deepcopy(value) if isinstance(value, dict) else None

    @property
    def historical_epochs(self) -> list[dict[str, Any]]:
        value = self.state.get("epochs", [])
        return deepcopy(value) if isinstance(value, list) else []

    @property
    def historical_frames(self) -> int:
        return sum(
            int(epoch["observation"]["frames_seen"])
            for epoch in self.state.get("epochs", [])
            if isinstance(epoch, dict)
            and isinstance(epoch.get("observation"), dict)
        )

    @property
    def total_observed_frames(self) -> int:
        return self.historical_frames + int(self.state["observation"]["frames_seen"])

    def set_checkpoint(self, checkpoint: dict[str, Any], *, save: bool = True) -> bool:
        normalized: dict[str, Any] = {
            "device": int(checkpoint["device"]),
            "inode": int(checkpoint["inode"]),
            "offset": int(checkpoint["offset"]),
        }
        if "anchor_start" in checkpoint and "anchor_sha256" in checkpoint:
            normalized["anchor_start"] = int(checkpoint["anchor_start"])
            normalized["anchor_sha256"] = str(checkpoint["anchor_sha256"])
        changed = self.state.get("checkpoint") != normalized
        self.state["checkpoint"] = normalized
        if changed:
            self.state["updated_at"] = _utc_now()
            if save:
                self.save()
        return changed

    def clear_checkpoint(self, *, reason: str | None = None, save: bool = True) -> None:
        self.state["checkpoint"] = None
        if reason:
            continuity = self.state.setdefault("continuity", {"resets": []})
            resets = continuity.setdefault("resets", [])
            resets.append({"at": _utc_now(), "reason": reason})
        self.state["updated_at"] = _utc_now()
        if save:
            self.save()

    @property
    def total_events(self) -> int:
        return int(self.state.get("total_events", 0))
