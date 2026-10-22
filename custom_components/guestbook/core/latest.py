"""Which entry the buttons and the optional `entry_id` of the actions mean: the latest one."""

from __future__ import annotations

from collections.abc import Iterable

from .models import Entry, EntryKind

CORRECTABLE_KINDS = (EntryKind.VISIT, EntryKind.UNANSWERED_RING)


def latest_entry(entries: Iterable[Entry]) -> Entry | None:
    """Return the entry with the most recent start whose stored decision is a visit or an unanswered ring.

    Open and closed entries count. Pending rings (still waiting for their window) and resident arrivals never do.
    The stored decision and start are used, not the correction, so an entry stays the latest one after it was
    corrected and can be corrected again. Of two entries with the same start, the one stored last wins.
    """
    latest: Entry | None = None
    for entry in entries:
        if entry.kind in CORRECTABLE_KINDS and (latest is None or entry.start >= latest.start):
            latest = entry
    return latest
