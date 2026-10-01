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


def test_watch_accepts_state_path():
    args = build_parser().parse_args(
        [
            "watch",
            "--profile",
            "hw5103-open-evidence",
            "--state",
            "/tmp/evidence-state.json",
        ]
    )
    assert args.state == "/tmp/evidence-state.json"


def test_watch_state_defaults_to_none():
    args = build_parser().parse_args(
        ["watch", "--profile", "hw5103-open-evidence"]
    )
    assert args.state is None


def test_watch_accepts_checkpoint_reset_flag():
    args = build_parser().parse_args(
        [
            "watch",
            "--profile",
            "hw5103-open-evidence",
            "--state",
            "/tmp/evidence-state.json",
            "--reset-checkpoint",
        ]
    )
    assert args.state == "/tmp/evidence-state.json"
    assert args.reset_checkpoint is True


def test_watch_state_flush_interval_defaults_to_five_seconds():
    args = build_parser().parse_args(
        ["watch", "--profile", "hw5103-open-evidence"]
    )
    assert args.state_flush_interval == 5.0


def test_watch_accepts_custom_state_flush_interval():
    args = build_parser().parse_args(
        [
            "watch",
            "--profile",
            "hw5103-open-evidence",
            "--state-flush-interval",
            "12.5",
        ]
    )
    assert args.state_flush_interval == 12.5


def test_watch_accepts_context_directory():
    args = build_parser().parse_args(
        [
            "watch",
            "--profile",
            "hw5103-open-evidence",
            "--context-dir",
            "/tmp/contexts",
        ]
    )
    assert args.context_dir == "/tmp/contexts"


def test_watch_context_directory_defaults_to_none():
    args = build_parser().parse_args(
        ["watch", "--profile", "hw5103-open-evidence"]
    )
    assert args.context_dir is None
