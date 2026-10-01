from __future__ import annotations

import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_STATE_FORMAT = "ebus-evidence-state-v1"


class StateError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


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
        "profile_version": profile.get("version", 1),
        "created_at": now,
        "updated_at": now,
        "total_events": 0,
        "checkpoint": None,
        "continuity": {
            "resets": [],
        },
        "checks": {
            check["id"]: _new_check(check)
            for check in profile["checks"]
        },
    }


def _validate_state(state: dict[str, Any], profile: dict[str, Any]) -> None:
    if state.get("format") != _STATE_FORMAT:
        raise StateError("unsupported state format")
    if state.get("profile") != profile["name"]:
        raise StateError(
            f"state profile mismatch: {state.get('profile')!r} != {profile['name']!r}"
        )
    if state.get("profile_version") != profile.get("version", 1):
        raise StateError(
            "state profile version mismatch: "
            f"{state.get('profile_version')!r} != {profile.get('version', 1)!r}"
        )
    if not isinstance(state.get("checks"), dict):
        raise StateError("state checks must be a mapping")

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


def load_state(path: str | Path, profile: dict[str, Any]) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return new_state(profile)
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StateError(f"cannot read state: {exc}") from exc
    if not isinstance(data, dict):
        raise StateError("state root must be a mapping")

    # Backward-compatible additions to state-v1.
    data.setdefault("checkpoint", None)
    data.setdefault("continuity", {"resets": []})
    if not isinstance(data["continuity"], dict):
        raise StateError("state continuity must be a mapping")
    data["continuity"].setdefault("resets", [])
    if not isinstance(data["continuity"]["resets"], list):
        raise StateError("state continuity resets must be a list")

    _validate_state(data, profile)

    # Allow descriptions/check ordering to evolve only when the profile
    # version was intentionally kept compatible.
    for check in profile["checks"]:
        data["checks"].setdefault(check["id"], _new_check(check))
    return data


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

    @classmethod
    def open(cls, path: str | Path, profile: dict[str, Any]) -> "EvidenceStateStore":
        state_path = Path(path)
        return cls(
            path=state_path,
            profile=profile,
            state=load_state(state_path, profile),
        )

    def save(self) -> None:
        save_state(self.path, self.state)

    def add(self, event: dict[str, Any], *, save: bool = True) -> None:
        update_state(self.state, event)
        if save:
            self.save()

    @property
    def checkpoint(self) -> dict[str, Any] | None:
        value = self.state.get("checkpoint")
        return deepcopy(value) if isinstance(value, dict) else None

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
