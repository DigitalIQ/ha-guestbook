"""Owns the engine and the store, schedules deadlines and tells listeners about changes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import uuid4

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_VISIT_CORRECTED,
    EVENT_VISIT_ENDED,
    EVENT_VISIT_EVENT,
    EVENT_VISIT_STARTED,
    SOURCE_ACTION,
)
from .core import (
    Certainty,
    Change,
    ChangeKind,
    Correction,
    EffectiveKind,
    Engine,
    Entry,
    EntryKind,
    Guest,
    Reason,
    Signal,
    effective_kind,
)
from .store import GuestbookStore


class GuestbookRuntime:
    def __init__(self, hass: HomeAssistant, store: GuestbookStore, engine: Engine, guests: list[Guest]) -> None:
        self._hass = hass
        self._guests = guests
        self._store = store
        self._engine = engine
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> None:
        now = dt_util.utcnow()
        self._apply(self._engine.advance(now))
        self._report_guests_away(now)
        self._announce_guests_at_home()

    async def async_stop(self) -> None:
        self._cancel_timer()
        await self._store.async_flush()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_set_guests(self, guests: list[Guest]) -> None:
        self._guests = guests
        self._engine.set_guests(guests)
        self._apply(self._engine.advance(dt_util.utcnow()))
        self._announce_guests_at_home()
        self._notify()

    @callback
    def _report_guests_away(self, now: datetime) -> None:
        """Count phones that are away at startup as having left now; their restored visits then run out."""
        for guest in self._guests:
            for tracker in guest.trackers:
                state = self._hass.states.get(tracker)
                if state is not None and state.state not in (STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN):
                    self._apply(self._engine.guest_absent(guest.id, tracker, now))

    @callback
    def _announce_guests_at_home(self) -> None:
        """Start a visit for every guest whose phone is already home and who is in no open visit."""
        now = dt_util.utcnow()
        for guest in self._guests:
            for tracker in guest.trackers:
                if (state := self._hass.states.get(tracker)) is not None and state.state == STATE_HOME:
                    self._apply(self._engine.guest_present(guest.id, tracker, now))
                    break

    @callback
    def async_handle_signal(self, signal: Signal) -> None:
        self._apply(self._engine.handle(signal))

    @callback
    def async_entries(self, *kinds: EffectiveKind) -> list[Entry]:
        """Return the entries whose effective kind (correction over decision) is one of `kinds`."""
        return [entry for entry in self._store.entries if effective_kind(entry) in kinds]

    @callback
    def async_open_visits(self) -> list[Entry]:
        """Return the open visits, the most recent first."""
        visits = (entry for entry in self.async_entries(EffectiveKind.VISIT) if entry.open)
        return sorted(visits, key=lambda entry: entry.start, reverse=True)

    @callback
    def async_correct_entry(
        self,
        entry_id: str,
        kind: str,
        *,
        guest_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        note: str | None = None,
        source: str = SOURCE_ACTION,
    ) -> Entry:
        """Store a correction next to the decision; resident and delivery close an open visit."""
        entry = self._entry(entry_id)
        if entry.kind is EntryKind.PENDING_RING:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_pending",
                translation_placeholders={"entry_id": entry_id},
            )
        self._check_times(start or entry.start, end or entry.end)
        now = dt_util.utcnow()
        entry.correction = Correction(kind, now, source, guest_name, start, end, note)
        self._store.async_put(entry)
        if kind in ("resident", "delivery"):
            self._apply(self._engine.close(entry.id, now))
        self._hass.bus.async_fire(EVENT_VISIT_CORRECTED, {"entry_id": entry.id, "kind": kind, "guest_name": guest_name})
        self._notify()
        return entry

    @callback
    def async_add_visit(self, guests: list[str], start: datetime, end: datetime, note: str | None = None) -> Entry:
        """Log a visit the sensors missed. Names that match a guest profile (any case) use it."""
        self._check_times(start, end)
        profiles = {guest.name.casefold(): guest for guest in self._guests}
        members: dict[str, dict[str, str]] = {}
        for name in (n.strip() for n in guests if n.strip()):
            profile = profiles.get(name.casefold())
            members.setdefault(
                name.casefold(), {"id": profile.id, "name": profile.name} if profile else {"id": "", "name": name}
            )
        entry = Entry(
            id=uuid4().hex,
            kind=EntryKind.VISIT,
            start=start,
            end=end,
            certainty=Certainty.CERTAIN,
            guests=list(members.values()),
            reason=Reason("manual", "Added by hand"),
            notes=[note] if note else [],
            settings=self._engine.settings.to_dict(),
        )
        self._store.async_put(entry)
        self._notify()
        return entry

    @callback
    def async_add_note(self, entry_id: str, note: str) -> Entry:
        entry = self._entry(entry_id)
        entry.notes.append(note)
        self._store.async_put(entry)
        self._notify()
        return entry

    def _entry(self, entry_id: str) -> Entry:
        for entry in self._store.entries:
            if entry.id == entry_id:
                return entry
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_entry", translation_placeholders={"entry_id": entry_id}
        )

    @staticmethod
    def _check_times(start: datetime, end: datetime | None) -> None:
        if end is not None and end <= start:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="end_before_start")

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _apply(self, changes: list[Change]) -> None:
        for change in changes:
            if change.kind is ChangeKind.CLOSED and change.entry.kind is EntryKind.PENDING_RING:
                self._store.async_remove(change.entry.id)
            else:
                self._store.async_put(change.entry)
            self._fire_event(change)
        self._schedule()
        if changes:
            self._notify()

    @callback
    def _fire_event(self, change: Change) -> None:
        entry = change.entry
        if change.previous is not None and change.previous.kind is EntryKind.VISIT and entry.end is not None:
            self._fire_ended(change.previous, entry.end, entry.kind.value)
            return
        if entry.kind is not EntryKind.VISIT:
            return
        data = self._event_data(entry)
        if change.kind in (ChangeKind.OPENED, ChangeKind.CLASSIFIED) and entry.open:
            self._hass.bus.async_fire(EVENT_VISIT_STARTED, {**data, "start": entry.start.isoformat()})
        elif change.kind is ChangeKind.SIGNAL_ADDED and change.signal is not None:
            signal = {"signal": change.signal.kind.value, "source": change.signal.source}
            self._hass.bus.async_fire(EVENT_VISIT_EVENT, {**data, **signal, "time": change.signal.time.isoformat()})
        elif change.kind is ChangeKind.CLOSED and entry.end is not None:
            self._fire_ended(entry, entry.end, entry.end_reason.code if entry.end_reason else "")

    @callback
    def _fire_ended(self, visit: Entry, end: datetime, reason: str) -> None:
        data = {
            **self._event_data(visit),
            "start": visit.start.isoformat(),
            "end": end.isoformat(),
            "duration": int((end - visit.start).total_seconds()),
            "reason": reason,
        }
        self._hass.bus.async_fire(EVENT_VISIT_ENDED, data)

    @staticmethod
    def _event_data(entry: Entry) -> dict[str, Any]:
        return {
            "entry_id": entry.id,
            "guests": [guest["name"] for guest in entry.guests],
            "certainty": entry.certainty.value if entry.certainty else None,
        }

    @callback
    def _schedule(self) -> None:
        self._cancel_timer()
        if (deadline := self._engine.next_deadline()) is not None:
            self._unsub_timer = async_track_point_in_utc_time(self._hass, self._async_deadline_reached, deadline)

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _async_deadline_reached(self, now) -> None:
        self._unsub_timer = None
        self._apply(self._engine.advance(now))
