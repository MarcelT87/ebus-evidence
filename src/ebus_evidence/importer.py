from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ebus_evidence.context import ContextCaptureManager
from ebus_evidence.input.raw_file import RawNonFrame, RawParseError, parse_record, split_records
from ebus_evidence.state import EvidenceStateStore
from ebus_evidence.timeutil import normalize_timestamp
from ebus_evidence.watch import frame_events


class StaticImportError(RuntimeError):
    pass


@dataclass(slots=True)
class ImportStats:
    frames: int = 0
    matches: int = 0
    non_frames: int = 0
    skipped: int = 0
    context_triggers: int = 0
    context_captures: int = 0
    source_files: int = 0
    non_frame_kinds: Counter[str] = field(default_factory=Counter)
    skip_reasons: Counter[str] = field(default_factory=Counter)


def _fingerprint(path: Path) -> tuple[int, int, int, int]:
    stat = path.stat()
    return (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns)


def import_sources(
    sources: list[Path],
    profile: dict[str, Any],
    store: EvidenceStateStore,
    *,
    context_dir: str | Path,
    source_timezone: str | None = None,
    display_timezone: str | None = None,
) -> ImportStats:
    """Import complete existing raw-log files into a fresh evidence state.

    Sources must remain unchanged for the duration of the import. This keeps
    offline/static import semantics distinct from live collection.
    """
    stats = ImportStats()
    context_manager = ContextCaptureManager(context_dir, profile)

    for source in sources:
        before = _fingerprint(source)
        stats.source_files += 1

        for record in split_records(source):
            context_manager.observe(record)
            try:
                frame = parse_record(record)
            except RawNonFrame as exc:
                stats.non_frames += 1
                stats.non_frame_kinds[exc.kind] += 1
                store.observe_non_frame(save=False)
                continue
            except RawParseError as exc:
                stats.skipped += 1
                stats.skip_reasons[str(exc)] += 1
                store.observe_skip(save=False)
                continue

            stats.frames += 1
            store.observe_frame(
                normalize_timestamp(
                    frame.timestamp,
                    source_timezone=source_timezone,
                    display_timezone=display_timezone,
                ),
                initiated_by_ebusd=frame.initiated_by_ebusd,
                save=False,
            )

            for event in frame_events(
                frame,
                profile,
                source_timezone=source_timezone,
                display_timezone=display_timezone,
            ):
                stats.matches += 1
                context_manager.trigger_event(event)
                store.add(event, save=False)

        after = _fingerprint(source)
        if after != before:
            raise StaticImportError(
                f"raw source changed during import: {source}; "
                "use a static copy for import or ./evidence collect for a growing file"
            )

    context_manager.finish()
    stats.context_triggers = context_manager.triggered
    stats.context_captures = context_manager.completed
    return stats
