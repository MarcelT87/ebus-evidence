from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


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
    document = build_system_document(
        devices,
        declared_manufacturer=declared_manufacturer,
        declared_model=declared_model,
    )

    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(document, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    try:
        output.write_text(payload, encoding="utf-8")
    except OSError as exc:
        raise SystemIdentityError(f"cannot write system document: {exc}") from exc

    return document
