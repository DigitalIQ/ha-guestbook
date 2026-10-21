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

RESIDENT_SIGNAL = Reason("resident_signal", "Resident signal close to the ring")
DOOR_THEN_QUIET = Reason("door_then_quiet", "Door opening followed by the quiet period")
MAX_DURATION = Reason("max_duration", "No end detected, ended at the maximum duration")

VISIT_SIGNALS = {
    SignalKind.DOOR_OPEN,
    SignalKind.DOOR_CLOSE,
    SignalKind.PRESENCE_ON,
    SignalKind.PRESENCE_OFF,
    SignalKind.LOCK,
}


class Engine:
    def __init__(self, settings: Settings, guests: list[Guest], entries: Iterable[Entry] = ()) -> None:
        self._settings = settings
        self._guests = guests
        self._residents: list[Signal] = []  # recent resident signals, kept in memory only
        self._active: dict[str, Entry] = {
            entry.id: entry
            for entry in entries
            if entry.open and entry.kind in (EntryKind.PENDING_RING, EntryKind.VISIT)
        }

    def handle(self, signal: Signal) -> list[Change]:
        changes = self.advance(signal.time)
        if signal.kind is SignalKind.RING:
            changes.append(self._handle_ring(signal))
        elif signal.kind is SignalKind.RESIDENT:
            changes.extend(self._handle_resident(signal))
        elif signal.kind in RING_THEN and (classified := self._turn_pending_rings_into_visit(signal)):
            changes.extend(classified)
        elif signal.kind in VISIT_SIGNALS:
            changes.extend(self._append_to_open_visits(signal))
        return changes

    def advance(self, now: datetime) -> list[Change]:
        due = sorted(
            ((deadline, entry) for entry in self._active.values() if (deadline := self._deadline(entry)) <= now),
            key=lambda item: item[0],
        )
        changes = []
        for _, entry in due:
            del self._active[entry.id]
            if entry.kind is EntryKind.PENDING_RING:
                entry.end = self._deadline(entry)
                changes.append(Change(ChangeKind.CLOSED, entry))
            else:
                changes.append(self._end_visit(entry))
        return changes

    def next_deadline(self) -> datetime | None:
        return min((self._deadline(e) for e in self._active.values()), default=None)

    def active_entries(self) -> list[Entry]:
        return list(self._active.values())

    def set_settings(self, settings: Settings) -> None:
        self._settings = settings

    def set_guests(self, guests: list[Guest]) -> None:
        self._guests = guests

    def _deadline(self, entry: Entry) -> datetime:
        if entry.kind is EntryKind.PENDING_RING:
            return datetime.fromisoformat(entry.rule_state[DEADLINE])
        return self._visit_end(entry)[0]

    def _visit_end(self, visit: Entry) -> tuple[datetime, datetime, Reason]:
        """Return the deadline, the end time and the end reason of an open visit."""
        limit = visit.start + self._settings.max_duration
        candidate = self._end_candidate(visit)
        if candidate is not None and candidate.time + self._settings.quiet_period <= limit:
            return candidate.time + self._settings.quiet_period, candidate.time, DOOR_THEN_QUIET
        return limit, limit, MAX_DURATION

    def _end_candidate(self, visit: Entry) -> Signal | None:
        """The last door opening after the guest came in; the visit ends there if the door stays quiet."""
        entered = next((s for s in visit.signals if s.kind is not SignalKind.RING), None)
        if entered is None:
            return None
        openings = [
            s
            for s in visit.signals
            if s.kind is SignalKind.DOOR_OPEN and s.time >= entered.time + self._settings.entry_grace
        ]
        return max(openings, key=lambda s: s.time, default=None)

    def _end_visit(self, visit: Entry) -> Change:
        _, visit.end, visit.end_reason = self._visit_end(visit)
        return Change(ChangeKind.CLOSED, visit)

    def _append_to_open_visits(self, signal: Signal) -> list[Change]:
        changes = []
        for visit in self._active.values():
            if visit.kind is EntryKind.VISIT:
                visit.signals.append(signal)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    def _handle_ring(self, signal: Signal) -> Change:
        since = signal.time - self._settings.resident_window
        if recent := [r for r in self._residents if since <= r.time <= signal.time]:
            signals = sorted([*recent, signal], key=lambda s: s.time)
            entry = Entry(id=uuid4().hex, kind=EntryKind.PENDING_RING, start=signal.time, signals=signals)
            return self._resident_arrival(entry, signal.time, signal)
        return self._open_pending_ring(signal)

    def _handle_resident(self, signal: Signal) -> list[Change]:
        horizon = signal.time - self._settings.resident_window
        self._residents = [r for r in self._residents if r.time >= horizon]
        self._residents.append(signal)
        changes = []
        for entry in sorted(self._active.values(), key=lambda e: e.start):
            if entry.kind is EntryKind.PENDING_RING or self._started_by_ring_inside_window(entry, signal.time):
                self._active.pop(entry.id, None)
                entry.signals.append(signal)
                changes.append(self._resident_arrival(entry, signal.time, signal))
        return changes

    def _started_by_ring_inside_window(self, visit: Entry, now: datetime) -> bool:
        if visit.reason is None or visit.reason.code not in {r.code for r in RING_THEN.values()}:
            return False
        window = self._settings.ring_window
        return any(s.kind is SignalKind.RING and s.time <= now < s.time + window for s in visit.signals)

    def _resident_arrival(self, entry: Entry, end: datetime, signal: Signal) -> Change:
        entry.kind = EntryKind.RESIDENT_ARRIVAL
        entry.certainty = None
        entry.end = end
        entry.end_reason = None
        entry.reason = RESIDENT_SIGNAL
        entry.settings = self._settings.to_dict()
        entry.rule_state = {}
        return Change(ChangeKind.CLASSIFIED, entry, signal)

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
