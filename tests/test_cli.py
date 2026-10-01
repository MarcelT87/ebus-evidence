from ebus_evidence.cli import build_parser


def test_analyze_raw_is_optional_for_auto_discovery():
    args = build_parser().parse_args(
        ["analyze", "--profile", "hw5103-open-evidence"]
    )
    assert args.raw is None
    assert args.profile == "hw5103-open-evidence"


def test_doctor_accepts_bundled_profile_name():
    args = build_parser().parse_args(
        ["doctor", "--profile", "hw5103-open-evidence"]
    )
    assert args.raw is None
    assert args.profile == "hw5103-open-evidence"


def test_watch_raw_is_optional_for_auto_discovery():
    args = build_parser().parse_args(
        ["watch", "--profile", "hw5103-open-evidence", "--seconds", "10"]
    )
    assert args.raw is None
    assert args.profile == "hw5103-open-evidence"
    assert args.seconds == 10.0
