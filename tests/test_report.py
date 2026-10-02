from pathlib import Path

from ebus_evidence.input.raw_file import iter_frames
from ebus_evidence.models import Frame
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.report import analyze_frames, format_text, shareable_report


ROOT = Path(__file__).parents[1]


def test_profile_report_from_raw_fixture():
    profile = load_profile(ROOT / "profiles" / "hw5103-open-evidence.yaml")
    report = analyze_frames(iter_frames(ROOT / "tests" / "fixtures" / "sample.raw"), profile)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["format"] == "ebus-evidence-report-v2"
    assert report["total_frames"] == 5
    assert checks["hmu_a80e_nonzero"]["matches"] == 2
    assert checks["hmu_a80e_nonzero"]["decoded"] == 2
    assert checks["hmu_a80e_nonzero"]["no_response"] == 0
    assert checks["hmu_a80e_nonzero"]["nonzero"] == 1
    assert checks["hmu_a80e_nonzero"]["minimum"] == 0.0
    assert checks["hmu_a80e_nonzero"]["maximum"] == 5.5
    assert checks["vwzio_b512_states"]["matches"] == 2
    assert checks["vwzio_b512_states"]["distinct_values"] == [0, 5]
    response = checks["hmu_a80e_nonzero"]["top_responses"][0]
    assert response["first_seen"]["raw"] == "2026-10-01 10:00:00.000"
    assert response["first_seen"]["utc"] is None
    assert response["first_seen"]["display"] is None


def test_timestamp_timezone_normalization():
    profile = {
        "name": "test",
        "version": 1,
        "checks": [
            {
                "id": "ba08",
                "description": "ba08",
                "match": {
                    "source": "f1",
                    "target": "08",
                    "pbsb": "b509",
                    "request": "05540200ba08",
                },
            }
        ],
    }
    frame = Frame(
        timestamp="2026-09-27 00:03:03.064",
        direction="<",
        initiated_by_ebusd=False,
        source="f1",
        target="08",
        pbsb="b509",
        request="05540200ba08",
        response="080201ba0820000000",
    )
    report = analyze_frames(
        [frame],
        profile,
        source_timezone="UTC",
        display_timezone="Europe/Berlin",
    )
    seen = report["checks"][0]["top_responses"][0]["first_seen"]

    assert seen["raw"] == "2026-09-27 00:03:03.064"
    assert seen["utc"] == "2026-09-27T00:03:03.064Z"
    assert seen["display"] == "2026-09-27T02:03:03.064+02:00"

    text = format_text(report)
    assert "raw source=UTC, display=Europe/Berlin" in text
    assert "2026-09-27T02:03:03.064+02:00" in text


def test_missing_response_is_not_a_decode_error():
    profile = {
        "name": "test",
        "version": 1,
        "checks": [
            {
                "id": "response_value",
                "description": "response value",
                "match": {"source": "f1", "target": "08", "pbsb": "b509"},
                "value": {"from": "response", "type": "u8", "offset": 0},
            }
        ],
    }
    frame = Frame(
        timestamp="2026-10-01 10:00:00.000",
        direction="<",
        initiated_by_ebusd=False,
        source="f1",
        target="08",
        pbsb="b509",
        request="05540200a80e",
        response=None,
    )
    report = analyze_frames([frame], profile)
    check = report["checks"][0]

    assert check["decoded"] == 0
    assert check["no_response"] == 1
    assert check["decode_errors"] == 0
    assert check["top_responses"][0]["first_seen"]["raw"] == frame.timestamp
    text = format_text(report)
    assert "<none>" in text
    assert "no response: 1" in text
    assert frame.timestamp in text


def test_shareable_report_omits_absolute_raw_path():
    report = {
        "format": "ebus-evidence-report-v2",
        "raw_path": "/private/host/path/ebusd.raw",
        "raw_path_source": "manual",
        "source_files": ["ebusd.raw"],
        "checks": [],
    }

    exported = shareable_report(report)

    assert "raw_path" not in exported
    assert exported["raw_path_source"] == "manual"
    assert exported["source_files"] == ["ebusd.raw"]
    assert exported["privacy"] == {
        "absolute_paths_included": False,
        "absolute_timestamps_included": True,
    }
    assert report["raw_path"] == "/private/host/path/ebusd.raw"
