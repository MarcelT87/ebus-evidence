from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

from ebus_evidence.structure import StructureLimitError, validate_structure_limits


_SYSTEM_FORMAT = "ebus-evidence-system-v1"
_ADDRESS_RE = re.compile(r"^[0-9a-fA-F]{2}$")


class SystemIdentityError(ValueError):
    pass


def _normalize_device(device: dict[str, str]) -> dict[str, str]:
    return {
        "address": device["address"].strip().lower(),
        "manufacturer": device["manufacturer"].strip(),
        "id": device["id"].strip(),
        "sw": device["sw"].strip(),
        "hw": device["hw"].strip(),
    }


def parse_scan_result(text: str) -> list[dict[str, str]]:
    """Parse existing `ebusctl scan result` output without retaining extra columns."""
    devices_by_address: dict[str, dict[str, str]] = {}

    for line_number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line:
            continue

        fields = line.split(";")
        if len(fields) < 5:
            raise SystemIdentityError(
                f"scan result line {line_number} has fewer than 5 fields"
            )

        device = _normalize_device(
            {
                "address": fields[0],
                "manufacturer": fields[1],
                "id": fields[2],
                "sw": fields[3],
                "hw": fields[4],
            }
        )

        if not _ADDRESS_RE.fullmatch(device["address"]):
            raise SystemIdentityError(
                f"scan result line {line_number} has invalid address: "
                f"{device['address']!r}"
            )
        if not device["manufacturer"]:
            raise SystemIdentityError(
                f"scan result line {line_number} has empty manufacturer"
            )

        previous = devices_by_address.get(device["address"])
        if previous is not None and previous != device:
            raise SystemIdentityError(
                f"conflicting scan results for address {device['address']}"
            )
        devices_by_address[device["address"]] = device

    if not devices_by_address:
        raise SystemIdentityError("scan result contains no devices")

    return [
        devices_by_address[address]
        for address in sorted(devices_by_address, key=lambda value: int(value, 16))
    ]


def topology_signature(devices: list[dict[str, str]]) -> str:
    """Return a deterministic SHA-256 signature for the observed device topology."""
    canonical = [
        {
            "address": device["address"].strip().lower(),
            "manufacturer": device["manufacturer"].strip().casefold(),
            "id": device["id"].strip().casefold(),
            "sw": device["sw"].strip().casefold(),
            "hw": device["hw"].strip().casefold(),
        }
        for device in devices
    ]
    canonical.sort(
        key=lambda item: (
            int(item["address"], 16),
            item["manufacturer"],
            item["id"],
            item["sw"],
            item["hw"],
        )
    )
    payload = json.dumps(
        canonical,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_system_document(
    devices: list[dict[str, str]],
    *,
    declared_manufacturer: str | None = None,
    declared_model: str | None = None,
) -> dict[str, Any]:
    normalized = [_normalize_device(device) for device in devices]
    signature = topology_signature(normalized)

    document: dict[str, Any] = {
        "format": _SYSTEM_FORMAT,
        "topology_signature_sha256": signature,
        "devices": normalized,
        "source": {
            "type": "ebusctl-scan-result",
            "retained_fields": [
                "address",
                "manufacturer",
                "id",
                "sw",
                "hw",
            ],
            "extra_scan_columns_retained": False,
        },
    }

    declared: dict[str, str] = {}
    if declared_manufacturer is not None and declared_manufacturer.strip():
        declared["manufacturer"] = declared_manufacturer.strip()
    if declared_model is not None and declared_model.strip():
        declared["model"] = declared_model.strip()
    if declared:
        document["declared_product"] = declared

    return document


def validate_system_document(data: Any) -> dict[str, Any]:
    if not isinstance(data, dict):
        raise SystemIdentityError("system identity root must be a mapping")

    allowed_top = {
        "format",
        "topology_signature_sha256",
        "devices",
        "source",
        "declared_product",
    }
    unknown_top = set(data) - allowed_top
    if unknown_top:
        raise SystemIdentityError(
            "system identity has unsupported top-level fields: "
            + ", ".join(sorted(unknown_top))
        )

    if data.get("format") != _SYSTEM_FORMAT:
        raise SystemIdentityError("unsupported system identity format")

    devices = data.get("devices")
    if not isinstance(devices, list) or not devices:
        raise SystemIdentityError("system identity requires a non-empty devices list")

    normalized_devices: list[dict[str, str]] = []
    seen_addresses: dict[str, dict[str, str]] = {}
    required_device = {"address", "manufacturer", "id", "sw", "hw"}
    for index, item in enumerate(devices):
        if not isinstance(item, dict):
            raise SystemIdentityError(f"device {index} must be a mapping")
        if set(item) != required_device:
            raise SystemIdentityError(
                f"device {index} must contain only address/manufacturer/id/sw/hw"
            )
        if not all(isinstance(item[key], str) for key in required_device):
            raise SystemIdentityError(f"device {index} fields must all be strings")
        device = _normalize_device(item)
        if not _ADDRESS_RE.fullmatch(device["address"]):
            raise SystemIdentityError(f"device {index} has invalid address")
        if not device["manufacturer"]:
            raise SystemIdentityError(f"device {index} has empty manufacturer")
        previous = seen_addresses.get(device["address"])
        if previous is not None and previous != device:
            raise SystemIdentityError(
                f"conflicting devices for address {device['address']}"
            )
        seen_addresses[device["address"]] = device
        normalized_devices.append(device)

    normalized_devices = [
        seen_addresses[address]
        for address in sorted(seen_addresses, key=lambda value: int(value, 16))
    ]

    signature = data.get("topology_signature_sha256")
    expected_signature = topology_signature(normalized_devices)
    if (
        not isinstance(signature, str)
        or len(signature) != 64
        or any(ch not in "0123456789abcdef" for ch in signature)
    ):
        raise SystemIdentityError(
            "topology_signature_sha256 must be a lowercase SHA-256 hex digest"
        )
    if signature != expected_signature:
        raise SystemIdentityError("topology signature does not match devices")

    source = data.get("source")
    expected_source = {
        "type": "ebusctl-scan-result",
        "retained_fields": ["address", "manufacturer", "id", "sw", "hw"],
        "extra_scan_columns_retained": False,
    }
    if source != expected_source:
        raise SystemIdentityError(
            "system identity source metadata is unsupported or not privacy-minimized"
        )

    declared = data.get("declared_product")
    normalized_declared: dict[str, str] | None = None
    if declared is not None:
        if not isinstance(declared, dict):
            raise SystemIdentityError("declared_product must be a mapping")
        unknown_declared = set(declared) - {"manufacturer", "model"}
        if unknown_declared:
            raise SystemIdentityError(
                "declared_product has unsupported fields: "
                + ", ".join(sorted(unknown_declared))
            )
        normalized_declared = {}
        for key in ("manufacturer", "model"):
            if key not in declared:
                continue
            value = declared[key]
            if not isinstance(value, str) or not value.strip():
                raise SystemIdentityError(
                    f"declared_product {key} must be a non-empty string"
                )
            normalized_declared[key] = value.strip()
        if not normalized_declared:
            normalized_declared = None

    normalized: dict[str, Any] = {
        "format": _SYSTEM_FORMAT,
        "topology_signature_sha256": expected_signature,
        "devices": normalized_devices,
        "source": expected_source,
    }
    if normalized_declared is not None:
        normalized["declared_product"] = normalized_declared
    return normalized


def load_system_document(path: str | Path) -> dict[str, Any]:
    system_path = Path(path)
    if not system_path.is_file():
        raise SystemIdentityError(f"system identity file not found: {system_path}")
    try:
        data = json.loads(system_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemIdentityError(f"cannot read system identity: {exc}") from exc
    except RecursionError as exc:
        raise SystemIdentityError(
            "cannot read system identity: structure is too deeply nested"
        ) from exc
    try:
        validate_structure_limits(data, label="system identity")
    except StructureLimitError as exc:
        raise SystemIdentityError(str(exc)) from exc
    return validate_system_document(data)


def create_system_document(
    scan_result_path: str | Path,
    output_path: str | Path,
    *,
    declared_manufacturer: str | None = None,
    declared_model: str | None = None,
) -> dict[str, Any]:
    source = Path(scan_result_path)
    if not source.is_file():
        raise SystemIdentityError(f"scan result file not found: {source}")

    try:
        text = source.read_text(encoding="utf-8")
    except OSError as exc:
        raise SystemIdentityError(f"cannot read scan result file: {exc}") from exc

    devices = parse_scan_result(text)
    document = validate_system_document(
        build_system_document(
            devices,
            declared_manufacturer=declared_manufacturer,
            declared_model=declared_model,
        )
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        output.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise SystemIdentityError(f"cannot write system document: {exc}") from exc

    return document
