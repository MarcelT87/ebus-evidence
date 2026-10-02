from __future__ import annotations

from pathlib import Path

from ebus_evidence.bundle import BundleError, create_bundle, verify_bundle
from ebus_evidence.discovery.ebusd import discover_ebusd
from ebus_evidence.profiles.loader import ProfileError, load_profile
from ebus_evidence.state import EvidenceStateStore, StateError
from ebus_evidence.system_identity import SystemIdentityError, load_system_document
from ebus_evidence.timeutil import TimezoneError, get_timezone
from ebus_evidence.watch import ResumeError, run_watch


DEFAULT_PROFILE = "hw5103-open-evidence"
DEFAULT_STATE = "data/evidence-state.json"
DEFAULT_CONTEXT_DIR = "data/contexts"
DEFAULT_SYSTEM = "data/system.json"
DEFAULT_EXPORT = "data/evidence.zip"


def _validate_timezones(source_timezone: str | None, display_timezone: str | None) -> None:
    get_timezone(source_timezone)
    get_timezone(display_timezone)


def _resolve_raw_path(raw_path: str | None) -> tuple[str, str]:
    if raw_path:
        path = Path(raw_path)
        if not path.is_file():
            raise FileNotFoundError(path)
        return str(path), "manual"

    discovery = discover_ebusd()
    if discovery is None:
        raise RuntimeError(
            "ebusd was not detected; use --raw /path/to/ebusd.raw"
        )
    if not discovery.raw_enabled:
        raise RuntimeError(
            "ebusd raw logging is not enabled; run 'ebus-evidence doctor' for details"
        )
    if discovery.raw_mode == "bytes":
        raise RuntimeError(
            "ebusd uses byte-level raw logging; message mode is required"
        )
    if discovery.raw_file_host is None:
        if discovery.installation == "docker":
            raise RuntimeError(
                "ebusd raw-log container path could not be mapped to the host; "
                "use --raw /host/path/ebusd.raw"
            )
        raise RuntimeError(
            "ebusd --lograwdatafile was not found; use --raw /path/to/ebusd.raw"
        )
    return discovery.raw_file_host, f"auto:{discovery.installation}"


def collect(
    *,
    raw_path: str | None = None,
    profile_name: str = DEFAULT_PROFILE,
    state_path: str = DEFAULT_STATE,
    context_dir: str = DEFAULT_CONTEXT_DIR,
    seconds: float | None = None,
    reset_checkpoint: bool = False,
    state_flush_interval: float = 5.0,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
) -> int:
    try:
        _validate_timezones(source_timezone, display_timezone)
        profile = load_profile(profile_name)
        resolved_raw, raw_source = _resolve_raw_path(raw_path)
    except (TimezoneError, ProfileError, FileNotFoundError, RuntimeError) as exc:
        print(f"error: {exc}")
        return 2

    if state_flush_interval <= 0:
        print("error: --state-flush-interval must be greater than zero")
        return 2

    state_file = Path(state_path)
    contexts = Path(context_dir)
    state_file.parent.mkdir(parents=True, exist_ok=True)
    contexts.mkdir(parents=True, exist_ok=True)

    try:
        store = EvidenceStateStore.open(state_file, profile)
        if reset_checkpoint:
            store.clear_checkpoint(
                reason="user acknowledged a resume gap with --reset-checkpoint"
            )
    except StateError as exc:
        print(f"error: cannot open evidence state: {exc}")
        return 2

    existing_frames = int(store.state["observation"]["frames_seen"])

    print("eBUS Evidence collection")
    print()
    print(f"Raw log ............. {resolved_raw} ({raw_source})")
    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")
    print(f"Evidence state ...... {state_file}")
    print(f"Contexts ............ {contexts}")
    print(f"Previously observed . {existing_frames} frames")
    print()
    print("Mode: passive / read-only")
    if seconds is None:
        print("Press Ctrl-C to stop.")
    else:
        print(f"Runtime limit: {seconds:g} seconds")
    print()

    try:
        stats = run_watch(
            resolved_raw,
            profile,
            source_timezone=source_timezone,
            display_timezone=display_timezone,
            seconds=seconds,
            state_store=store,
            state_flush_interval=state_flush_interval,
            context_dir=contexts,
        )
    except ResumeError as exc:
        print(f"error: cannot resume collection safely: {exc}")
        print(
            "hint: inspect the gap first; if it is acceptable, rerun with "
            "--reset-checkpoint"
        )
        return 2
    except (OSError, StateError) as exc:
        print(f"error: cannot collect from raw log: {exc}")
        return 2

    try:
        final_store = EvidenceStateStore.open(state_file, profile)
    except StateError as exc:
        print(f"error: cannot reopen saved evidence state: {exc}")
        return 2

    observation = final_store.state["observation"]
    print()
    print("Collection complete.")
    print()
    print(f"Frames observed ...... {observation['frames_seen']}")
    print(f"Passive frames ....... {observation['passive_frames']}")
    print(f"ebusd initiated ....... {observation['ebusd_initiated_frames']}")
    print(f"Evidence events ....... {final_store.total_events}")
    print(f"Contexts captured ..... {stats.context_captures}")
    print(f"Non-frames ............ {observation['non_frames']}")
    print(f"Skipped ............... {observation['skipped']}")
    print(f"Resume mode ........... {stats.resume_mode}")
    print()
    print(f"State saved: {state_file}")
    print()
    print("Next:")
    print("  ./evidence export")
    return 0


def status(
    *,
    raw_path: str | None = None,
    profile_name: str = DEFAULT_PROFILE,
    state_path: str = DEFAULT_STATE,
    context_dir: str = DEFAULT_CONTEXT_DIR,
    system_path: str = DEFAULT_SYSTEM,
) -> int:
    try:
        profile = load_profile(profile_name)
    except ProfileError as exc:
        print(f"error: {exc}")
        return 2

    print("eBUS Evidence status")
    print()

    try:
        resolved_raw, raw_source = _resolve_raw_path(raw_path)
    except (FileNotFoundError, RuntimeError) as exc:
        print(f"Raw log ............. not ready ({exc})")
    else:
        print(f"Raw log ............. ready ({resolved_raw}, {raw_source})")

    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")

    state_file = Path(state_path)
    state_ready = False
    state_has_observation = False
    if state_file.is_file():
        try:
            store = EvidenceStateStore.open(state_file, profile)
        except StateError as exc:
            print(f"Evidence state ...... invalid ({exc})")
        else:
            state_ready = True
            observation = store.state["observation"]
            state_has_observation = int(observation["frames_seen"]) > 0
            print(f"Evidence state ...... present ({state_file})")
            print(f"Frames observed ..... {observation['frames_seen']}")
            print(f"Evidence events ..... {store.total_events}")
            first = observation.get("first_frame_timestamp")
            last = observation.get("last_frame_timestamp")
            if isinstance(first, dict):
                print(f"First observation ... {first.get('display') or first.get('raw')}")
            if isinstance(last, dict):
                print(f"Last observation .... {last.get('display') or last.get('raw')}")
    else:
        print(f"Evidence state ...... missing ({state_file})")

    contexts = Path(context_dir)
    context_count = (
        len(list(contexts.glob("*.json")))
        if contexts.is_dir()
        else 0
    )
    print(f"Context metadata .... {context_count}")

    system_file = Path(system_path)
    if system_file.is_file():
        try:
            system = load_system_document(system_file)
        except SystemIdentityError as exc:
            print(f"System identity ..... invalid ({exc})")
        else:
            print(
                f"System identity ..... present "
                f"({len(system['devices'])} devices)"
            )
    else:
        print("System identity ..... absent (optional)")

    ready = state_has_observation or context_count > 0
    print()
    print(f"Ready to export ..... {'YES' if ready else 'NO'}")
    if ready:
        print()
        print("Next:")
        print("  ./evidence export")
    else:
        print()
        print("Next:")
        print("  ./evidence collect")
    return 0


def export(
    *,
    profile_name: str = DEFAULT_PROFILE,
    state_path: str = DEFAULT_STATE,
    context_dir: str = DEFAULT_CONTEXT_DIR,
    system_path: str = DEFAULT_SYSTEM,
    output_path: str = DEFAULT_EXPORT,
    include_context_raw: bool = False,
) -> int:
    try:
        profile = load_profile(profile_name)
    except ProfileError as exc:
        print(f"error: {exc}")
        return 2

    state_file = Path(state_path)
    contexts = Path(context_dir)
    system_file = Path(system_path)
    output = Path(output_path)

    state_arg = state_file if state_file.is_file() else None
    context_arg = contexts if contexts.is_dir() else None
    system_arg = system_file if system_file.is_file() else None
    context_count = (
        len(list(contexts.glob("*.json")))
        if context_arg is not None
        else 0
    )

    state_frames = 0
    if state_arg is not None:
        try:
            store = EvidenceStateStore.open(state_arg, profile)
        except StateError as exc:
            print(f"error: collected evidence state is invalid: {exc}")
            return 2
        state_frames = int(store.state["observation"]["frames_seen"])

    if state_frames == 0 and context_count == 0:
        print("error: no observed evidence is ready to export")
        if state_arg is not None:
            print(
                "hint: the state exists but contains 0 observed frames; "
                "run './evidence collect' while the raw log is growing"
            )
        else:
            print("hint: run './evidence collect' first")
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)

    print("eBUS Evidence export")
    print()
    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")
    print(f"Evidence state ...... {'included' if state_arg else 'not present'}")
    print(
        f"Context metadata .... "
        f"{context_count}"
    )
    print(f"System identity ..... {'included' if system_arg else 'not present'}")
    print(
        f"Raw context ......... "
        f"{'INCLUDED (explicit request)' if include_context_raw else 'excluded'}"
    )
    print()

    try:
        created = create_bundle(
            output,
            profile,
            state_path=state_arg,
            context_dir=context_arg,
            system_path=system_arg,
            include_context_raw=include_context_raw,
        )
        verified = verify_bundle(output)
    except BundleError as exc:
        print(f"error: export failed: {exc}")
        return 2

    print(f"Output .............. {output}")
    print(f"Status .............. {'VALID' if verified['valid'] else 'INVALID'}")
    print(
        f"Deterministic ....... "
        f"{'yes' if verified['deterministic_layout'] else 'no'}"
    )
    print(
        f"State included ...... "
        f"{'yes' if verified['state_included'] else 'no'}"
    )
    print(
        f"System identity ..... "
        f"{'yes' if verified['system_identity_included'] else 'no'}"
    )
    print(f"Context metadata .... {verified['context_metadata_count']}")
    print(f"Raw context ......... {verified['context_raw_count']}")
    if verified.get("absolute_timestamps_included") is True:
        print("Absolute timestamps . yes")
    print(f"SHA256 .............. {created['sha256']}")
    print()
    print("Ready to share.")
    return 0
