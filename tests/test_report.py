from pathlib import Path

from ebus_evidence.input.raw_file import iter_frames
from ebus_evidence.models import Frame
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.report import analyze_frames, format_text


ROOT = Path(__file__).parents[1]


def test_profile_report_from_raw_fixture():
    profile = load_profile(ROOT / "profiles" / "hw5103-open-evidence.yaml")
    report = analyze_frames(iter_frames(ROOT / "tests" / "fixtures" / "sample.raw"), profile)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["total_frames"] == 5
    assert checks["hmu_a80e_nonzero"]["matches"] == 2
    assert checks["hmu_a80e_nonzero"]["decoded"] == 2
    assert checks["hmu_a80e_nonzero"]["no_response"] == 0
    assert checks["hmu_a80e_nonzero"]["nonzero"] == 1
    assert checks["hmu_a80e_nonzero"]["minimum"] == 0.0
    assert checks["hmu_a80e_nonzero"]["maximum"] == 5.5
    assert checks["vwzio_b512_states"]["matches"] == 2
    assert checks["vwzio_b512_states"]["distinct_values"] == [0, 5]


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
    text = format_text(report)
    assert "<none>" in text
    assert "no response: 1" in text
