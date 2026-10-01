from ebus_evidence.matching import frame_matches
from ebus_evidence.models import Frame


def frame() -> Frame:
    return Frame(
        timestamp="2026-10-01 10:00:00.000",
        direction="<",
        initiated_by_ebusd=False,
        source="03",
        target="76",
        pbsb="b512",
        request="0613000c710405",
        response="0202ff",
    )


def test_exact_and_prefix_matching():
    assert frame_matches(frame(), {"source": "03", "target": "76", "pbsb": "b512"})
    assert frame_matches(frame(), {"request_prefix": "0613"})
    assert not frame_matches(frame(), {"request": "061300"})
