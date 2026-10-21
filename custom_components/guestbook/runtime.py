"""Owns the engine and the store, schedules deadlines and tells listeners about changes."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from homeassistant.const import STATE_HOME
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import EVENT_VISIT_ENDED, EVENT_VISIT_EVENT, EVENT_VISIT_STARTED
from .core import Change, ChangeKind, Engine, Entry, EntryKind, Guest, Signal
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
        self._apply(self._engine.advance(dt_util.utcnow()))
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
        for listener in list(self._listeners):
            listener()

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
    def async_entries(self, kind: EntryKind) -> list[Entry]:
        return [entry for entry in self._store.entries if entry.kind is kind]

    @callback
    def async_open_visits(self) -> list[Entry]:
        """Return the open visits, the most recent first."""
        visits = (entry for entry in self.async_entries(EntryKind.VISIT) if entry.open)
        return sorted(visits, key=lambda entry: entry.start, reverse=True)

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
            for listener in list(self._listeners):
                listener()

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
