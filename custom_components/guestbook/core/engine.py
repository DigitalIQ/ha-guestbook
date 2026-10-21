"""The rule core. It never reads the clock; time moves through signals and advance()."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta
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
UNANSWERED_RING_LENGTH = timedelta(minutes=1)  # calendar length of the short event

RING_THEN: dict[SignalKind, Reason] = {
    SignalKind.DOOR_OPEN: Reason("ring_then_door", "Ring followed by a door opening within the ring window"),
    SignalKind.PRESENCE_ON: Reason("ring_then_presence", "Ring followed by presence within the ring window"),
}

RING_NO_ENTRY = Reason("ring_no_entry", "No door opening, presence or resident signal in the ring window")
RESIDENT_SIGNAL = Reason("resident_signal", "Resident signal close to the ring")
DOOR_THEN_QUIET = Reason("door_then_quiet", "Door opening followed by the quiet period")
MAX_DURATION = Reason("max_duration", "No end detected, ended at the maximum duration")
GUEST_PHONE = Reason("guest_phone", "Guest phone joined the network")
GUESTS_LEFT = Reason("guests_left", "All guest phones left")

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
        elif signal.kind is SignalKind.GUEST_HOME:
            changes.extend(self._handle_guest_home(signal))
        elif signal.kind is SignalKind.GUEST_AWAY:
            changes.extend(self._append_to_visits_of_guest(signal))
        elif signal.kind in RING_THEN and (classified := self._turn_pending_rings_into_visit(signal)):
            changes.extend(classified)
        elif signal.kind in VISIT_SIGNALS:
            changes.extend(self._append_to_open_visits(signal))
        return changes

    def advance(self, now: datetime) -> list[Change]:
        due = sorted(
            (
                (deadline, entry)
                for entry in self._active.values()
                if (deadline := self._deadline(entry)) is not None and deadline <= now
            ),
            key=lambda item: item[0],
        )
        changes = []
        for _, entry in due:
            del self._active[entry.id]
            if entry.kind is EntryKind.PENDING_RING:
                changes.append(self._unanswered_ring(entry))
            else:
                changes.append(self._end_visit(entry))
        return changes

    def next_deadline(self) -> datetime | None:
        return min((d for e in self._active.values() if (d := self._deadline(e)) is not None), default=None)

    def active_entries(self) -> list[Entry]:
        return list(self._active.values())

    def set_settings(self, settings: Settings) -> None:
        self._settings = settings

    def set_guests(self, guests: list[Guest]) -> None:
        self._guests = guests

    def _deadline(self, entry: Entry) -> datetime | None:
        if entry.kind is EntryKind.PENDING_RING:
            return datetime.fromisoformat(entry.rule_state[DEADLINE])
        end = self._visit_end(entry)
        return end[0] if end else None

    def _visit_end(self, visit: Entry) -> tuple[datetime, datetime, Reason] | None:
        """Return the deadline, the end time and the end reason of an open visit, None while a phone is home."""
        if visit.certainty is Certainty.CERTAIN:
            return self._phone_end(visit)
        limit = visit.start + self._settings.max_duration
        candidate = self._end_candidate(visit)
        if candidate is not None and candidate.time + self._settings.quiet_period <= limit:
            return candidate.time + self._settings.quiet_period, candidate.time, DOOR_THEN_QUIET
        return limit, limit, MAX_DURATION

    def _phone_end(self, visit: Entry) -> tuple[datetime, datetime, Reason] | None:
        """A certain visit ends when its last guest phone has been away for the grace period."""
        known = {tracker for guest in self._guests for tracker in guest.trackers}
        last: dict[str, Signal] = {}
        for s in visit.signals:
            if s.kind in (SignalKind.GUEST_HOME, SignalKind.GUEST_AWAY):
                last[s.source] = s
        if any(s.kind is SignalKind.GUEST_HOME and s.source in known for s in last.values()):
            return None
        left = max((s.time for s in last.values()), default=visit.start)
        return left + self._settings.phone_grace, left, GUESTS_LEFT

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

    def _handle_guest_home(self, signal: Signal) -> list[Change]:
        guest = next((g for g in self._guests if g.id == signal.guest_id), None)
        if guest is None:
            return []
        visits = sorted((e for e in self._active.values() if e.kind is EntryKind.VISIT), key=lambda e: e.start)
        member = {"id": guest.id, "name": guest.name}
        certain_first = sorted(visits, key=lambda v: v.certainty is not Certainty.CERTAIN)
        visit = next((v for v in visits if member in v.guests), None) or next(iter(certain_first), None)
        if visit is None:
            return [self._open_phone_visit(signal, member)]
        if member not in visit.guests:
            visit.guests.append(member)
        visit.certainty = Certainty.CERTAIN
        visit.signals.append(signal)
        return [Change(ChangeKind.SIGNAL_ADDED, visit, signal)]

    def _open_phone_visit(self, signal: Signal, member: dict[str, str]) -> Change:
        visit = Entry(
            id=uuid4().hex,
            kind=EntryKind.VISIT,
            start=signal.time,
            certainty=Certainty.CERTAIN,
            guests=[member],
            signals=[signal],
            reason=GUEST_PHONE,
            settings=self._settings.to_dict(),
        )
        self._active[visit.id] = visit
        return Change(ChangeKind.OPENED, visit, signal)

    def _append_to_visits_of_guest(self, signal: Signal) -> list[Change]:
        changes = []
        for visit in self._active.values():
            if visit.kind is EntryKind.VISIT and any(g["id"] == signal.guest_id for g in visit.guests):
                visit.signals.append(signal)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    def _append_to_open_visits(self, signal: Signal) -> list[Change]:
        changes = []
        for visit in self._active.values():
            if visit.kind is EntryKind.VISIT:
                visit.signals.append(signal)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    def _unanswered_ring(self, ring: Entry) -> Change:
        ring.kind = EntryKind.UNANSWERED_RING
        ring.end = ring.start + UNANSWERED_RING_LENGTH
        ring.reason = RING_NO_ENTRY
        ring.settings = self._settings.to_dict()
        ring.rule_state = {}
        return Change(ChangeKind.CLASSIFIED, ring)

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
        if visit.certainty is not Certainty.UNCERTAIN or visit.reason is None:
            return False
        if visit.reason.code not in {r.code for r in RING_THEN.values()}:
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
        if certain := next((e for e in self._active.values() if e.certainty is Certainty.CERTAIN), None):
            return self._join_certain_visit(certain, pending, signal)
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

    def _join_certain_visit(self, visit: Entry, pending: list[Entry], signal: Signal) -> list[Change]:
        changes = []
        for ring in pending:
            del self._active[ring.id]
            visit.signals.extend(ring.signals)
            ring.end = signal.time
            changes.append(Change(ChangeKind.CLOSED, ring))
        visit.signals.append(signal)
        visit.signals.sort(key=lambda s: s.time)
        changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes
