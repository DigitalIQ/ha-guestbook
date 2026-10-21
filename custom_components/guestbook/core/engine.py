"""The rule core. It never reads the clock; time moves through signals and advance()."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from .models import (
    Certainty,
    Change,
    ChangeKind,
    Entry,
    EntryKind,
    Guest,
    Reason,
    Settings,
    Signal,
    SignalKind,
)

DEADLINE = "deadline"

RING_THEN: dict[SignalKind, Reason] = {
    SignalKind.DOOR_OPEN: Reason("ring_then_door", "Ring followed by a door opening within the ring window"),
    SignalKind.PRESENCE_ON: Reason("ring_then_presence", "Ring followed by presence within the ring window"),
}


class Engine:
    def __init__(self, settings: Settings, guests: list[Guest], entries: Iterable[Entry] = ()) -> None:
        self._settings = settings
        self._guests = guests
        self._active: dict[str, Entry] = {
            entry.id: entry
            for entry in entries
            if entry.open and entry.kind in (EntryKind.PENDING_RING, EntryKind.VISIT)
        }

    def handle(self, signal: Signal) -> list[Change]:
        changes = self.advance(signal.time)
        if signal.kind is SignalKind.RING:
            changes.append(self._open_pending_ring(signal))
        elif signal.kind in RING_THEN:
            changes.extend(self._turn_pending_rings_into_visit(signal))
        return changes

    def advance(self, now: datetime) -> list[Change]:
        changes = []
        for entry in list(self._active.values()):
            if entry.kind is EntryKind.PENDING_RING and self._deadline(entry) <= now:
                del self._active[entry.id]
                entry.end = self._deadline(entry)
                changes.append(Change(ChangeKind.CLOSED, entry))
        return changes

    def next_deadline(self) -> datetime | None:
        deadlines = [self._deadline(e) for e in self._active.values() if e.kind is EntryKind.PENDING_RING]
        return min(deadlines, default=None)

    def active_entries(self) -> list[Entry]:
        return list(self._active.values())

    def set_settings(self, settings: Settings) -> None:
        self._settings = settings

    def set_guests(self, guests: list[Guest]) -> None:
        self._guests = guests

    @staticmethod
    def _deadline(entry: Entry) -> datetime:
        return datetime.fromisoformat(entry.rule_state[DEADLINE])

    def _open_pending_ring(self, signal: Signal) -> Change:
        entry = Entry(
            id=uuid4().hex,
            kind=EntryKind.PENDING_RING,
            start=signal.time,
            signals=[signal],
            settings=self._settings.to_dict(),
            rule_state={DEADLINE: (signal.time + self._settings.ring_window).isoformat()},
        )
        self._active[entry.id] = entry
        return Change(ChangeKind.OPENED, entry, signal)

    def _turn_pending_rings_into_visit(self, signal: Signal) -> list[Change]:
        pending = sorted((e for e in self._active.values() if e.kind is EntryKind.PENDING_RING), key=lambda e: e.start)
        if not pending:
            return []
        visit, *others = pending
        changes = []
        for other in others:
            del self._active[other.id]
            visit.signals.extend(other.signals)
            other.end = signal.time
            changes.append(Change(ChangeKind.CLOSED, other))
        visit.signals.sort(key=lambda s: s.time)
        visit.signals.append(signal)
        visit.kind = EntryKind.VISIT
        visit.certainty = Certainty.UNCERTAIN
        visit.reason = RING_THEN[signal.kind]
        visit.settings = self._settings.to_dict()
        visit.rule_state = {}
        changes.append(Change(ChangeKind.CLASSIFIED, visit, signal))
        return changes
