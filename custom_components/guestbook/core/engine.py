"""The rule core. It never reads the clock; time moves through signals and advance()."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from datetime import datetime, timedelta
from uuid import uuid4

from .models import (
    LEFT_GUESTS,
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
MAX_SIGNALS = 1000  # signals kept per entry; an open visit must not grow without bound
RING_WAKE_UP_DELAY = timedelta(seconds=1)  # a timer for a ring window waits this long so signals at the end arrive

RING_THEN: dict[SignalKind, Reason] = {
    SignalKind.DOOR_OPEN: Reason("ring_then_door", "Ring followed by a door opening within the ring window"),
    SignalKind.PRESENCE_ON: Reason("ring_then_presence", "Ring followed by presence within the ring window"),
}

RING_NO_ENTRY = Reason("ring_no_entry", "No door opening, presence or resident signal in the ring window")
RESIDENT_SIGNAL = Reason("resident_signal", "Resident signal close to the ring")
DOOR_THEN_QUIET = Reason("door_then_quiet", "Door opening followed by the quiet period")
MAX_DURATION = Reason("max_duration", "No end detected, ended at the maximum duration")
GUEST_PHONE = Reason("guest_phone", "Guest phone joined the network")
GUEST_PHONE_AT_START = Reason("guest_phone_at_start", "Guest phone was already on the network at startup")
GUESTS_LEFT = Reason("guests_left", "All guest phones left")
CORRECTED = Reason("corrected", "Closed by a correction")

VISIT_SIGNALS = {
    SignalKind.DOOR_OPEN,
    SignalKind.DOOR_CLOSE,
    SignalKind.PRESENCE_ON,
    SignalKind.PRESENCE_OFF,
    SignalKind.LOCK,
}

PHONE_SIGNALS = {SignalKind.GUEST_HOME, SignalKind.GUEST_AWAY}
DROPPABLE_SIGNALS = VISIT_SIGNALS  # rings, phone signals and the signal that started the visit are never dropped


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
        changes = self._advance(signal.time, ring_window_inclusive=signal.kind in RING_THEN)
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

    def guest_present(self, guest_id: str, tracker: str, now: datetime) -> list[Change]:
        """Report a guest phone that is already home (startup, new guest).

        A visit that has the guest only learns of phones it has not seen yet and of a pending leave of this phone,
        which is cancelled.
        """
        changes = self.advance(now)
        signal = Signal(SignalKind.GUEST_HOME, now, tracker, "home", guest_id)
        holders = [
            v for v in self._active.values() if v.kind is EntryKind.VISIT and any(g["id"] == guest_id for g in v.guests)
        ]
        if not holders:
            return [*changes, *self._handle_guest_home(signal, GUEST_PHONE_AT_START)]
        guest = next((g for g in self._guests if g.id == guest_id), None)
        for visit in holders:
            if guest is not None:
                self._rename_member(visit, guest)
            last = self._last_phone_signal(visit, tracker)
            if last is None or last.kind is SignalKind.GUEST_AWAY:
                self._add_signal(visit, signal)
                self._welcome_back(visit, guest_id)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    def guest_absent(self, guest_id: str, tracker: str, now: datetime) -> list[Change]:
        """Report a guest phone that is not home at startup; visits that last saw it home get an away signal."""
        signal = Signal(SignalKind.GUEST_AWAY, now, tracker, guest_id=guest_id)
        changes = []
        for visit in self._active.values():
            last = self._last_phone_signal(visit, tracker)
            if visit.kind is EntryKind.VISIT and last is not None and last.kind is SignalKind.GUEST_HOME:
                self._add_signal(visit, signal)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    @staticmethod
    def _last_phone_signal(visit: Entry, tracker: str) -> Signal | None:
        return next((s for s in reversed(visit.signals) if s.source == tracker and s.kind in PHONE_SIGNALS), None)

    def advance(self, now: datetime) -> list[Change]:
        """Fire the deadlines up to `now`. A pending ring survives `now` equal to the end of its window."""
        return self._advance(now, ring_window_inclusive=True)

    def _advance(self, now: datetime, *, ring_window_inclusive: bool) -> list[Change]:
        """Fire the deadlines up to `now`; a door opening or presence at the end of a ring window still counts.

        A ring whose window ends exactly at `now` expires only for a signal that cannot start a visit.
        """

        def reached(deadline: datetime, entry: Entry) -> bool:
            return deadline < now or (
                deadline == now and not (ring_window_inclusive and entry.kind is EntryKind.PENDING_RING)
            )

        due: list[tuple[datetime, int, Entry, str | None]] = []
        for entry in self._active.values():
            if (deadline := self._deadline(entry)) is not None and reached(deadline, entry):
                due.append((deadline, 0, entry, None))
            if entry.kind is EntryKind.VISIT:
                due.extend(
                    (deadline, 1, entry, guest_id)
                    for deadline, guest_id in self._guest_leaves(entry)
                    if reached(deadline, entry)
                )
        due.sort(key=lambda item: item[:2])  # at the same time a visit ends before a guest of it leaves
        changes = []
        for _, _, entry, guest_id in due:
            if entry.id not in self._active:
                continue
            if guest_id is not None:
                entry.rule_state[LEFT_GUESTS] = [*entry.rule_state.get(LEFT_GUESTS, ()), guest_id]
                changes.append(Change(ChangeKind.GUEST_LEFT, entry))
                continue
            del self._active[entry.id]
            if entry.kind is EntryKind.PENDING_RING:
                changes.append(self._unanswered_ring(entry))
            else:
                changes.append(self._end_visit(entry))
        return changes

    def next_deadline(self) -> datetime | None:
        """The earliest time at which `advance` has something to do; a ring window is waited out a moment longer."""
        return min((d for e in self._active.values() if (d := self._wake_up(e)) is not None), default=None)

    def _wake_up(self, entry: Entry) -> datetime | None:
        deadline = self._deadline(entry)
        if deadline is not None and entry.kind is EntryKind.PENDING_RING:
            return deadline + RING_WAKE_UP_DELAY
        leaves = [leave for leave, _ in self._guest_leaves(entry)] if entry.kind is EntryKind.VISIT else []
        return min([*leaves, *([deadline] if deadline is not None else [])], default=None)

    def close(self, entry_id: str, now: datetime) -> list[Change]:
        """End an open visit at `now` (a correction made it no visit); pending rings are left alone."""
        visit = self._active.get(entry_id)
        if visit is None or visit.kind is not EntryKind.VISIT:
            return []
        del self._active[entry_id]
        visit.end, visit.end_reason = now, CORRECTED
        return [Change(ChangeKind.CLOSED, visit)]

    @property
    def settings(self) -> Settings:
        return self._settings

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

    def _guest_leaves(self, visit: Entry) -> list[tuple[datetime, str]]:
        """When each guest still counted as present leaves the visit: all phones away for the phone grace."""
        left = visit.rule_state.get(LEFT_GUESTS, ())
        leaves = []
        for member in visit.guests:
            guest_id = member["id"]
            if not guest_id or guest_id in left:
                continue
            last: dict[str, Signal] = {}
            for s in visit.signals:
                if s.kind in PHONE_SIGNALS and s.guest_id == guest_id:
                    last[s.source] = s
            trackers = next((g.trackers for g in self._guests if g.id == guest_id), [])
            if any(s.kind is SignalKind.GUEST_HOME and s.source in trackers for s in last.values()):
                continue
            gone = max((s.time for s in last.values()), default=visit.start)
            leaves.append((gone + self._settings.phone_grace, guest_id))
        return leaves

    @staticmethod
    def _rename_member(visit: Entry, guest: Guest) -> None:
        """Guests are members of a visit by id; a rename shows in the visit the next time the guest is seen."""
        for member in visit.guests:
            if member["id"] == guest.id:
                member["name"] = guest.name

    @staticmethod
    def _welcome_back(visit: Entry, guest_id: str) -> None:
        if guest_id in visit.rule_state.get(LEFT_GUESTS, ()):
            visit.rule_state[LEFT_GUESTS] = [g for g in visit.rule_state[LEFT_GUESTS] if g != guest_id]

    @staticmethod
    def _add_signal(visit: Entry, signal: Signal) -> None:
        """Append a signal; beyond `MAX_SIGNALS` the oldest door, presence and lock signals are dropped and counted."""
        visit.signals.append(signal)
        excess = len(visit.signals) - MAX_SIGNALS
        if excess <= 0:
            return
        starter = next((i for i, s in enumerate(visit.signals) if s.kind is not SignalKind.RING), None)
        kept, dropped = [], 0
        for index, kept_signal in enumerate(visit.signals):
            if dropped < excess and index != starter and kept_signal.kind in DROPPABLE_SIGNALS:
                dropped += 1
            else:
                kept.append(kept_signal)
        visit.signals[:] = kept
        visit.dropped_signals += dropped

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

    def _handle_guest_home(self, signal: Signal, reason: Reason = GUEST_PHONE) -> list[Change]:
        guest = next((g for g in self._guests if g.id == signal.guest_id), None)
        if guest is None:
            return []
        visits = sorted((e for e in self._active.values() if e.kind is EntryKind.VISIT), key=lambda e: e.start)
        member = {"id": guest.id, "name": guest.name}
        certain_first = sorted(visits, key=lambda v: v.certainty is not Certainty.CERTAIN)
        visit = next((v for v in visits if any(g["id"] == guest.id for g in v.guests)), None) or next(
            iter(certain_first), None
        )
        if visit is None:
            return [self._open_phone_visit(signal, member, reason)]
        if not any(g["id"] == guest.id for g in visit.guests):
            visit.guests.append(member)
        self._rename_member(visit, guest)
        self._welcome_back(visit, guest.id)
        visit.certainty = Certainty.CERTAIN
        self._add_signal(visit, signal)
        return [Change(ChangeKind.SIGNAL_ADDED, visit, signal)]

    def _open_phone_visit(self, signal: Signal, member: dict[str, str], reason: Reason) -> Change:
        visit = Entry(
            id=uuid4().hex,
            kind=EntryKind.VISIT,
            start=signal.time,
            certainty=Certainty.CERTAIN,
            guests=[member],
            signals=[signal],
            reason=reason,
            settings=self._settings.to_dict(),
        )
        self._active[visit.id] = visit
        return Change(ChangeKind.OPENED, visit, signal)

    def _append_to_visits_of_guest(self, signal: Signal) -> list[Change]:
        """An away signal only counts for a visit that last saw this phone home."""
        changes = []
        for visit in self._active.values():
            last = self._last_phone_signal(visit, signal.source)
            if (
                visit.kind is EntryKind.VISIT
                and any(g["id"] == signal.guest_id for g in visit.guests)
                and last is not None
                and last.kind is SignalKind.GUEST_HOME
            ):
                self._add_signal(visit, signal)
                changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes

    def _append_to_open_visits(self, signal: Signal) -> list[Change]:
        changes = []
        for visit in self._active.values():
            if visit.kind is EntryKind.VISIT:
                self._add_signal(visit, signal)
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
        previous = replace(entry)
        entry.kind = EntryKind.RESIDENT_ARRIVAL
        entry.certainty = None
        entry.end = end
        entry.end_reason = None
        entry.reason = RESIDENT_SIGNAL
        entry.settings = self._settings.to_dict()
        entry.rule_state = {}
        return Change(ChangeKind.CLASSIFIED, entry, signal, previous)

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
        visit.signals.sort(key=lambda s: s.time)
        self._add_signal(visit, signal)
        changes.append(Change(ChangeKind.SIGNAL_ADDED, visit, signal))
        return changes
