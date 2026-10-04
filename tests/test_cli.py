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


def test_bundle_accepts_state_context_and_output():
    args = build_parser().parse_args(
        [
            "bundle",
            "--profile",
            "hw5103-open-evidence",
            "--state",
            "/tmp/state.json",
            "--context-dir",
            "/tmp/contexts",
            "--system",
            "/tmp/system.json",
            "--output",
            "/tmp/evidence.zip",
        ]
    )
    assert args.profile == "hw5103-open-evidence"
    assert args.state == "/tmp/state.json"
    assert args.context_dir == "/tmp/contexts"
    assert args.system == "/tmp/system.json"
    assert args.output == "/tmp/evidence.zip"
    assert args.include_context_raw is False
    assert args.no_context_raw is False


def test_bundle_can_explicitly_include_context_raw():
    args = build_parser().parse_args(
        [
            "bundle",
            "--profile",
            "hw5103-open-evidence",
            "--context-dir",
            "/tmp/contexts",
            "--include-context-raw",
            "--output",
            "/tmp/evidence.zip",
        ]
    )
    assert args.include_context_raw is True
    assert args.no_context_raw is False


def test_bundle_accepts_legacy_no_context_raw_flag():
    args = build_parser().parse_args(
        [
            "bundle",
            "--profile",
            "hw5103-open-evidence",
            "--context-dir",
            "/tmp/contexts",
            "--no-context-raw",
            "--output",
            "/tmp/evidence.zip",
        ]
    )
    assert args.no_context_raw is True


def test_verify_accepts_bundle_path():
    args = build_parser().parse_args(
        ["verify", "/tmp/evidence.zip"]
    )
    assert args.bundle == "/tmp/evidence.zip"


def test_system_accepts_existing_scan_result_and_declared_product():
    args = build_parser().parse_args(
        [
            "system",
            "--scan-result",
            "/tmp/scan-result.txt",
            "--manufacturer",
            "Vaillant",
            "--model",
            "TEST-MODEL",
            "--output",
            "/tmp/system.json",
        ]
    )
    assert args.scan_result == "/tmp/scan-result.txt"
    assert args.manufacturer == "Vaillant"
    assert args.model == "TEST-MODEL"
    assert args.output == "/tmp/system.json"


def test_collect_uses_beginner_defaults():
    args = build_parser().parse_args(["collect"])
    assert args.raw is None
    assert args.profile == "hw5103-open-evidence"
    assert args.state == "data/evidence-state.json"
    assert args.context_dir == "data/contexts"
    assert args.seconds is None


def test_status_uses_beginner_defaults():
    args = build_parser().parse_args(["status"])
    assert args.profile == "hw5103-open-evidence"
    assert args.state == "data/evidence-state.json"
    assert args.context_dir == "data/contexts"
    assert args.system == "data/system.json"


def test_export_uses_beginner_defaults():
    args = build_parser().parse_args(["export"])
    assert args.profile == "hw5103-open-evidence"
    assert args.state == "data/evidence-state.json"
    assert args.context_dir == "data/contexts"
    assert args.system == "data/system.json"
    assert args.output == "data/evidence.zip"
    assert args.include_context_raw is False


def test_verify_accepts_submission_policy_flag():
    args = build_parser().parse_args(
        ["verify", "--submission", "/tmp/evidence.zip"]
    )
    assert args.bundle == "/tmp/evidence.zip"
    assert args.submission is True
