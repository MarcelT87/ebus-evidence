from pathlib import Path

from ebus_evidence.input.raw_file import iter_frames
from ebus_evidence.profiles.loader import load_profile
from ebus_evidence.report import analyze_frames


ROOT = Path(__file__).parents[1]


def test_profile_report_from_raw_fixture():
    profile = load_profile(ROOT / "profiles" / "hw5103-open-evidence.yaml")
    report = analyze_frames(iter_frames(ROOT / "tests" / "fixtures" / "sample.raw"), profile)
    checks = {item["id"]: item for item in report["checks"]}

    assert report["total_frames"] == 5
    assert checks["hmu_a80e_nonzero"]["matches"] == 2
    assert checks["hmu_a80e_nonzero"]["decoded"] == 2
    assert checks["hmu_a80e_nonzero"]["nonzero"] == 1
    assert checks["hmu_a80e_nonzero"]["minimum"] == 0.0
    assert checks["hmu_a80e_nonzero"]["maximum"] == 5.5
    assert checks["vwzio_b512_states"]["matches"] == 2
    assert checks["vwzio_b512_states"]["distinct_values"] == [0, 5]
