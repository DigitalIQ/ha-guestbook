"""Owns the engine and the store, schedules deadlines and tells listeners about changes."""

from __future__ import annotations

from collections.abc import Callable

from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .core import Change, ChangeKind, Engine, Entry, EntryKind, Signal
from .store import GuestbookStore


class GuestbookRuntime:
    def __init__(self, hass: HomeAssistant, store: GuestbookStore, engine: Engine) -> None:
        self._hass = hass
        self._store = store
        self._engine = engine
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> None:
        self._apply(self._engine.advance(dt_util.utcnow()))

    async def async_stop(self) -> None:
        self._cancel_timer()
        await self._store.async_flush()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_handle_signal(self, signal: Signal) -> None:
        self._apply(self._engine.handle(signal))

    @callback
    def async_entries(self, kind: EntryKind) -> list[Entry]:
        return [entry for entry in self._store.entries if entry.kind is kind]

    @callback
    def _apply(self, changes: list[Change]) -> None:
        for change in changes:
            if change.kind is ChangeKind.CLOSED and change.entry.kind is EntryKind.PENDING_RING:
                self._store.async_remove(change.entry.id)
            else:
                self._store.async_put(change.entry)
        self._schedule()
        if changes:
            for listener in list(self._listeners):
                listener()

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
