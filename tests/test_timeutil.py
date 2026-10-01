import pytest

from ebus_evidence.timeutil import TimezoneError, normalize_timestamp


def test_normalize_timestamp_preserves_raw_and_adds_utc():
    result = normalize_timestamp(
        "2026-09-27 00:03:03.064",
        source_timezone="UTC",
        display_timezone="Europe/Berlin",
    )
    assert result == {
        "raw": "2026-09-27 00:03:03.064",
        "utc": "2026-09-27T00:03:03.064Z",
        "display": "2026-09-27T02:03:03.064+02:00",
    }


def test_normalize_timestamp_without_timezone_does_not_guess():
    result = normalize_timestamp("2026-09-27 00:03:03.064")
    assert result["raw"] == "2026-09-27 00:03:03.064"
    assert result["utc"] is None
    assert result["display"] is None


def test_unknown_timezone_is_rejected():
    with pytest.raises(TimezoneError):
        normalize_timestamp(
            "2026-09-27 00:03:03.064",
            source_timezone="Not/A_Real_Zone",
        )
