from __future__ import annotations

from pathlib import Path
import shutil
import tempfile

from ebus_evidence.bundle import BundleError, create_bundle, verify_bundle
from ebus_evidence.context import ContextError, context_metadata_scope
from ebus_evidence.discovery.ebusd import discover_ebusd
from ebus_evidence.importer import StaticImportError, import_sources
from ebus_evidence.input.raw_file import resolve_raw_sources
from ebus_evidence.profiles.loader import ProfileError, load_profile
from ebus_evidence.state import (
    EvidenceStateStore,
    ProfileRolloverRequired,
    StateError,
    load_state,
)
from ebus_evidence.system_identity import SystemIdentityError, load_system_document
from ebus_evidence.timeutil import TimezoneError, get_timezone
from ebus_evidence.watch import ResumeError, run_watch


DEFAULT_PROFILE = "hw5103-open-evidence"
DEFAULT_STATE = "data/evidence-state.json"
DEFAULT_CONTEXT_DIR = "data/contexts"
DEFAULT_SYSTEM = "data/system.json"
DEFAULT_EXPORT = "data/evidence.zip"


def _restore_empty_context_destination(
    contexts: Path,
    *,
    existed_before: bool,
) -> None:
    if contexts.exists():
        if contexts.is_dir():
            shutil.rmtree(contexts)
        else:
            contexts.unlink()
    if existed_before:
        contexts.mkdir(parents=True, exist_ok=False)


def _publish_static_import_outputs(
    *,
    temp_state: Path,
    temp_contexts: Path,
    state_file: Path,
    contexts: Path,
    contexts_existed_before: bool,
) -> None:
    """Publish a completed static import with failure rollback.

    Contexts are published first and the state file last. The state therefore
    remains the commit marker for a completed import. If publishing the state
    fails after contexts were moved into place, the context destination is
    rolled back to the exact pre-import empty/absent condition.
    """

    contexts_touched = False
    try:
        if contexts.exists():
            contexts.rmdir()

        if temp_contexts.exists():
            temp_contexts.replace(contexts)
        else:
            contexts.mkdir(parents=True, exist_ok=False)
        contexts_touched = True

        temp_state.replace(state_file)
    except OSError as publish_error:
        rollback_error: OSError | None = None
        if contexts_touched or not contexts.exists():
            try:
                _restore_empty_context_destination(
                    contexts,
                    existed_before=contexts_existed_before,
                )
            except OSError as exc:
                rollback_error = exc

        if rollback_error is not None:
            raise OSError(
                "static import publish failed and context rollback also failed: "
                f"publish={publish_error}; rollback={rollback_error}"
            ) from publish_error
        raise


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
        store = EvidenceStateStore.open(
            state_file,
            profile,
            allow_profile_rollover=True,
        )
        if reset_checkpoint:
            store.clear_checkpoint(
                reason="user acknowledged a resume gap with --reset-checkpoint"
            )
    except StateError as exc:
        print(f"error: cannot open evidence state: {exc}")
        return 2

    existing_frames = int(store.state["observation"]["frames_seen"])
    historical_frames = store.historical_frames

    print("eBUS Evidence collection")
    print()
    print(f"Raw log ............. {resolved_raw} ({raw_source})")
    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")
    print(f"Evidence state ...... {state_file}")
    print(f"Contexts ............ {contexts}")
    print(f"Previously observed . {existing_frames} active frames")
    if historical_frames:
        print(
            f"Historical epochs ... {len(store.historical_epochs)} "
            f"({historical_frames} frames)"
        )
    if store.rolled_over_from is not None:
        print(
            f"Profile rollover .... v{store.rolled_over_from} -> "
            f"v{profile.get('version', 1)}"
        )
        print("Previous coverage was archived; the new epoch starts at 0 frames.")
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
    print(f"Frames observed ...... {observation['frames_seen']} (active epoch)")
    if final_store.historical_epochs:
        print(
            f"Historical epochs .... {len(final_store.historical_epochs)} "
            f"({final_store.historical_frames} frames)"
        )
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



def import_raw(
    *,
    raw_path: str,
    profile_name: str = DEFAULT_PROFILE,
    state_path: str = DEFAULT_STATE,
    context_dir: str = DEFAULT_CONTEXT_DIR,
    include_rotated: bool = False,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
) -> int:
    try:
        _validate_timezones(source_timezone, display_timezone)
        profile = load_profile(profile_name)
    except (TimezoneError, ProfileError) as exc:
        print(f"error: {exc}")
        return 2

    raw_file = Path(raw_path)
    if not raw_file.is_file():
        print(f"error: raw file not found: {raw_file}")
        return 2

    sources = resolve_raw_sources(raw_file, include_rotated=include_rotated)
    state_file = Path(state_path)
    contexts = Path(context_dir)

    if state_file.exists():
        print(f"error: existing evidence state found: {state_file}")
        print(
            "hint: static import requires a fresh state so observation histories "
            "are not mixed; archive the old state or choose --state NEWFILE"
        )
        return 2

    contexts_existed_before = contexts.exists()
    if contexts_existed_before:
        if not contexts.is_dir():
            print(f"error: context path is not a directory: {contexts}")
            return 2
        if any(contexts.iterdir()):
            print(f"error: existing context files found: {contexts}")
            print(
                "hint: static import requires an empty context destination so "
                "observation histories are not mixed"
            )
            return 2

    source_paths = {source.resolve() for source in sources}
    if state_file.resolve() in source_paths:
        print("error: evidence state path must not overwrite a raw source")
        return 2

    state_file.parent.mkdir(parents=True, exist_ok=True)
    contexts.parent.mkdir(parents=True, exist_ok=True)

    state_tmp_root = Path(
        tempfile.mkdtemp(prefix=".evidence-import-state-", dir=state_file.parent)
    )
    context_tmp_root = Path(
        tempfile.mkdtemp(prefix=".evidence-import-context-", dir=contexts.parent)
    )
    temp_state = state_tmp_root / "state.json"
    temp_contexts = context_tmp_root / "contexts"

    print("eBUS Evidence static import")
    print()
    print(f"Raw log ............. {raw_file} (read-only)")
    if include_rotated:
        print(f"Source files ........ {len(sources)}")
    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")
    print(f"Evidence state ...... {state_file}")
    print(f"Contexts ............ {contexts}")
    print()
    print("Mode: offline / read-only / from beginning to end")
    print("The source file must remain unchanged during import.")
    print()

    try:
        store = EvidenceStateStore.open(temp_state, profile)
        stats = import_sources(
            sources,
            profile,
            store,
            context_dir=temp_contexts,
            source_timezone=source_timezone,
            display_timezone=display_timezone,
        )
        if stats.frames == 0:
            print("error: no complete eBUS frames were found; import was not published")
            return 2

        store.save()

        _publish_static_import_outputs(
            temp_state=temp_state,
            temp_contexts=temp_contexts,
            state_file=state_file,
            contexts=contexts,
            contexts_existed_before=contexts_existed_before,
        )
    except (OSError, StateError, StaticImportError) as exc:
        print(f"error: static import failed: {exc}")
        return 2
    finally:
        shutil.rmtree(state_tmp_root, ignore_errors=True)
        shutil.rmtree(context_tmp_root, ignore_errors=True)

    print("Import complete.")
    print()
    print(f"Source files ......... {stats.source_files}")
    print(f"Frames observed ...... {stats.frames}")
    print(f"Evidence events ....... {stats.matches}")
    print(f"Contexts captured ..... {stats.context_captures}")
    print(f"Non-frames ............ {stats.non_frames}")
    print(f"Skipped ............... {stats.skipped}")
    if stats.non_frame_kinds:
        print("Non-frame kinds:")
        for kind, count in stats.non_frame_kinds.most_common():
            print(f"  {count:>8}  {kind}")
    if stats.skip_reasons:
        print("Skip reasons:")
        for reason, count in stats.skip_reasons.most_common():
            print(f"  {count:>8}  {reason}")
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
    state_has_observation = False
    state_invalid = False
    rollover_pending = False
    if state_file.is_file():
        try:
            store = EvidenceStateStore.open(state_file, profile)
        except ProfileRolloverRequired as exc:
            rollover_pending = True
            try:
                preview = load_state(
                    state_file,
                    profile,
                    allow_profile_rollover=True,
                )
            except StateError as preview_exc:
                state_invalid = True
                print(f"Evidence state ...... invalid ({preview_exc})")
            else:
                preview_epochs = preview.get("epochs", [])
                preview_historical_frames = sum(
                    int(epoch["observation"]["frames_seen"])
                    for epoch in preview_epochs
                    if isinstance(epoch, dict)
                    and isinstance(epoch.get("observation"), dict)
                )
                preview_active_frames = int(
                    preview.get("observation", {}).get("frames_seen", 0)
                )
                state_has_observation = (
                    preview_historical_frames + preview_active_frames
                ) > 0
                print(
                    "Evidence state ...... profile rollover pending "
                    f"(v{exc.current_version} -> v{exc.requested_version})"
                )
                print(
                    f"Historical epochs ... {len(preview_epochs)} "
                    f"({preview_historical_frames} frames after rollover)"
                )
                print(
                    "Rollover preview .... read-only; collect/watch persists it"
                )
        except StateError as exc:
            state_invalid = True
            print(f"Evidence state ...... invalid ({exc})")
        else:
            observation = store.state["observation"]
            state_has_observation = store.total_observed_frames > 0
            print(f"Evidence state ...... present ({state_file})")
            print(f"Frames observed ..... {observation['frames_seen']} (active epoch)")
            if store.historical_epochs:
                print(
                    f"Historical epochs ... {len(store.historical_epochs)} "
                    f"({store.historical_frames} frames)"
                )
            print(f"Evidence events ..... {store.total_events} (active epoch)")
            first = observation.get("first_frame_timestamp")
            last = observation.get("last_frame_timestamp")
            if isinstance(first, dict):
                print(f"First observation ... {first.get('display') or first.get('raw')}")
            if isinstance(last, dict):
                print(f"Last observation .... {last.get('display') or last.get('raw')}")
    else:
        print(f"Evidence state ...... missing ({state_file})")

    contexts = Path(context_dir)
    current_context_count = 0
    historical_context_count = 0
    context_invalid = False
    if contexts.is_dir():
        try:
            context_scope = context_metadata_scope(contexts, profile)
        except ContextError as exc:
            context_invalid = True
            print(f"Context metadata .... invalid ({exc})")
        else:
            current_context_count = len(context_scope.current)
            historical_context_count = len(context_scope.historical)
            print(f"Context metadata .... {current_context_count} current")
            if historical_context_count:
                print(
                    f"Historical contexts . {historical_context_count} "
                    "(kept local; excluded from current-profile export)"
                )
    else:
        print("Context metadata .... 0 current")

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

    ready = (
        (state_has_observation or current_context_count > 0)
        and not state_invalid
        and not context_invalid
    )
    print()
    print(f"Ready to export ..... {'YES' if ready else 'NO'}")
    if ready:
        print()
        print("Next:")
        print("  ./evidence export")
        if rollover_pending:
            print("  # export previews rollover read-only; collect persists it")
    else:
        print()
        print("Next:")
        if rollover_pending:
            print("  ./evidence collect   # starts the new profile observation epoch")
        else:
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

    current_context_count = 0
    historical_context_count = 0
    if context_arg is not None:
        try:
            context_scope = context_metadata_scope(contexts, profile)
        except ContextError as exc:
            print(f"error: context metadata is invalid: {exc}")
            return 2
        current_context_count = len(context_scope.current)
        historical_context_count = len(context_scope.historical)

    state_frames = 0
    rollover_preview: tuple[int, int] | None = None
    if state_arg is not None:
        try:
            store = EvidenceStateStore.open(state_arg, profile)
        except ProfileRolloverRequired as exc:
            try:
                preview = load_state(
                    state_arg,
                    profile,
                    allow_profile_rollover=True,
                )
            except StateError as preview_exc:
                print(f"error: collected evidence state is invalid: {preview_exc}")
                return 2
            rollover_preview = (exc.current_version, exc.requested_version)
            state_frames = int(preview["observation"]["frames_seen"]) + sum(
                int(epoch["observation"]["frames_seen"])
                for epoch in preview.get("epochs", [])
                if isinstance(epoch, dict)
                and isinstance(epoch.get("observation"), dict)
            )
        except StateError as exc:
            print(f"error: collected evidence state is invalid: {exc}")
            return 2
        else:
            state_frames = store.total_observed_frames

    if state_frames == 0 and current_context_count == 0:
        print("error: no observed evidence is ready to export")
        if state_arg is not None:
            print(
                "hint: the state exists but contains 0 observed frames; "
                "use './evidence collect' for a growing raw log, or import a "
                "static copy into a fresh state with './evidence import --raw FILE'"
            )
        else:
            print(
                "hint: run './evidence collect' for a growing raw log, or "
                "'./evidence import --raw FILE' for a static copy"
            )
        return 2

    output.parent.mkdir(parents=True, exist_ok=True)

    print("eBUS Evidence export")
    print()
    print(f"Profile ............. {profile['name']} (v{profile.get('version', 1)})")
    print(f"Evidence state ...... {'included' if state_arg else 'not present'}")
    if rollover_preview is not None:
        print(
            f"Profile rollover .... v{rollover_preview[0]} -> "
            f"v{rollover_preview[1]} (read-only preview)"
        )
        print("Local state ......... unchanged until collect/watch persists rollover")
    print(
        f"Context metadata .... "
        f"{current_context_count}"
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
    if historical_context_count:
        print(
            f"Historical contexts . {historical_context_count} "
            "(kept local; excluded)"
        )
    if verified.get("historical_epoch_count", 0):
        print(
            f"Historical epochs .... {verified['historical_epoch_count']} "
            f"({verified['historical_frames']} frames)"
        )
    print(f"Raw context ......... {verified['context_raw_count']}")
    provenance = verified.get("provenance")
    if isinstance(provenance, dict):
        runtime = provenance["tool_runtime"]
        print(f"Tool runtime SHA256 . {runtime['sha256']}")
        print(f"Profile SHA256 ...... {provenance['profile_sha256']}")
        git = provenance.get("git")
        if isinstance(git, dict):
            status = "dirty" if git["dirty"] else "clean"
            print(f"Source commit ....... {git['commit']} ({status})")
        else:
            print("Source commit ....... unavailable")
    if verified.get("absolute_timestamps_included") is True:
        print("Absolute timestamps . yes")
    print(f"SHA256 .............. {created['sha256']}")
    print()
    print("Ready to share.")
    return 0
