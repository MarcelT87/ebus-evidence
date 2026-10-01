from __future__ import annotations

import struct
from typing import Any

from ebus_evidence.models import Frame


class DecodeError(ValueError):
    pass


def _read_bytes(frame: Frame, spec: dict[str, Any]) -> bytes:
    source = str(spec.get("from", "response"))
    if source not in {"request", "response"}:
        raise DecodeError("value.from must be request or response")
    raw_hex = frame.request if source == "request" else frame.response
    if not raw_hex:
        raise DecodeError(f"frame has no {source}")
    try:
        return bytes.fromhex(raw_hex)
    except ValueError as exc:
        raise DecodeError(f"invalid {source} hex") from exc


def decode_value(frame: Frame, spec: dict[str, Any]) -> int | float | str:
    data = _read_bytes(frame, spec)
    try:
        offset = int(spec.get("offset", 0))
    except (TypeError, ValueError) as exc:
        raise DecodeError("value.offset must be an integer") from exc
    if offset < 0:
        raise DecodeError("value.offset must be >= 0")

    value_type = str(spec.get("type", "hex")).lower()
    sizes = {"u8": 1, "u16le": 2, "s16le": 2, "u32le": 4, "s32le": 4, "float32le": 4}

    if value_type == "hex":
        length = spec.get("length")
        if length is None:
            raw = data[offset:]
        else:
            raw = data[offset : offset + int(length)]
        if not raw:
            raise DecodeError("hex slice is empty")
        value: int | float | str = raw.hex()
    else:
        size = sizes.get(value_type)
        if size is None:
            raise DecodeError(f"unsupported value type: {value_type}")
        raw = data[offset : offset + size]
        if len(raw) != size:
            raise DecodeError("value extends beyond available bytes")
        if value_type == "u8":
            value = raw[0]
        elif value_type == "u16le":
            value = int.from_bytes(raw, "little", signed=False)
        elif value_type == "s16le":
            value = int.from_bytes(raw, "little", signed=True)
        elif value_type == "u32le":
            value = int.from_bytes(raw, "little", signed=False)
        elif value_type == "s32le":
            value = int.from_bytes(raw, "little", signed=True)
        else:
            value = struct.unpack("<f", raw)[0]

    if isinstance(value, (int, float)):
        if "divisor" in spec:
            value = value / float(spec["divisor"])
        if "multiplier" in spec:
            value = value * float(spec["multiplier"])
    return value
