"""Selection of entries for the retention purge and the JSONL export."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta

from .models import Entry, EntryKind

PRIVATE_FIELDS = ("rule_state", "question_token")


def expired_entries(entries: Iterable[Entry], now: datetime, retention: timedelta) -> list[Entry]:
    """Closed entries whose end is older than the retention; open entries are never expired."""
    cutoff = now - retention
    return [entry for entry in entries if entry.end is not None and entry.end < cutoff]


def entries_in_range(entries: Iterable[Entry], start: datetime | None, end: datetime | None) -> list[Entry]:
    """Entries sorted by start, limited to `start <= entry.start < end` (a missing bound is open).

    Pending rings are never part of it: they are unfinished and the rule engine may still turn them into something else.
    """
    chosen = (
        e
        for e in entries
        if e.kind is not EntryKind.PENDING_RING
        and (start is None or e.start >= start)
        and (end is None or e.start < end)
    )
    return sorted(chosen, key=lambda entry: entry.start)


def to_jsonl(entries: Iterable[Entry]) -> str:
    """One JSON object per line, without the private `rule_state` and the question token (both stay in the storage)."""
    lines = ({k: v for k, v in entry.to_dict().items() if k not in PRIVATE_FIELDS} for entry in entries)
    return "".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines)
