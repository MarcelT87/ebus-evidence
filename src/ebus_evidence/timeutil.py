from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


_RAW_FORMAT = "%Y-%m-%d %H:%M:%S.%f"


class TimezoneError(ValueError):
    pass


def get_timezone(name: str | None) -> ZoneInfo | None:
    if not name:
        return None
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError as exc:
        raise TimezoneError(f"unknown timezone: {name}") from exc


def normalize_timestamp(
    raw_timestamp: str,
    *,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
) -> dict[str, str | None]:
    """Preserve the raw timestamp and optionally attach timezone-aware forms."""
    result: dict[str, str | None] = {
        "raw": raw_timestamp,
        "utc": None,
        "display": None,
    }

    source = get_timezone(source_timezone)
    if source is None:
        return result

    try:
        parsed = datetime.strptime(raw_timestamp, _RAW_FORMAT).replace(tzinfo=source)
    except ValueError as exc:
        raise TimezoneError(f"invalid raw timestamp: {raw_timestamp}") from exc

    utc_value = parsed.astimezone(timezone.utc)
    result["utc"] = utc_value.isoformat(timespec="milliseconds").replace("+00:00", "Z")

    display = get_timezone(display_timezone) if display_timezone else source
    result["display"] = parsed.astimezone(display).isoformat(timespec="milliseconds")
    return result
