"""Selection of entries for the retention purge and the JSONL export."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime, timedelta

from .models import Entry


def expired_entries(entries: Iterable[Entry], now: datetime, retention: timedelta) -> list[Entry]:
    """Closed entries whose end is older than the retention; open entries are never expired."""
    cutoff = now - retention
    return [entry for entry in entries if entry.end is not None and entry.end < cutoff]


def entries_in_range(entries: Iterable[Entry], start: datetime | None, end: datetime | None) -> list[Entry]:
    """Entries sorted by start, limited to `start <= entry.start < end` (a missing bound is open)."""
    chosen = (e for e in entries if (start is None or e.start >= start) and (end is None or e.start < end))
    return sorted(chosen, key=lambda entry: entry.start)


def to_jsonl(entries: Iterable[Entry]) -> str:
    return "".join(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n" for entry in entries)
