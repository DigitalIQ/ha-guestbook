"""Turns state changes of the selected source entities into signals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.components.lock import LockState
from homeassistant.const import STATE_HOME, STATE_OFF, STATE_ON, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import CONF_DOORBELLS, CONF_DOORS, CONF_LOCKS, CONF_PRESENCE, CONF_RESIDENT_SIGNALS
from .core import Guest, Signal, SignalKind

STATE_IGNORED = {STATE_UNAVAILABLE, STATE_UNKNOWN}
RESIDENT_STATES = {STATE_ON, STATE_HOME, LockState.UNLOCKED}

type Converter = Callable[[str, State | None, State], Signal | None]


def _edge(old: State | None, new: State, before: str, after: str) -> bool:
    return old is not None and old.state == before and new.state == after


def _event(kind: SignalKind, entity_id: str, old: State | None, new: State) -> Signal | None:
    # An event entity is "unknown" until its first event, so unknown -> timestamp is a real event.
    if old is None or old.state == STATE_UNAVAILABLE or new.state == old.state:
        return None
    if dt_util.parse_datetime(new.state) is None:
        return None
    return Signal(kind, new.last_changed, entity_id)


def _changed(old: State | None, new: State) -> bool:
    return old is not None and STATE_IGNORED.isdisjoint((old.state, new.state)) and old.state != new.state


def _doorbell(entity_id: str, old: State | None, new: State) -> Signal | None:
    if entity_id.startswith("event."):
        return _event(SignalKind.RING, entity_id, old, new)
    if _edge(old, new, STATE_OFF, STATE_ON):
        return Signal(SignalKind.RING, new.last_changed, entity_id)
    return None


def _door(entity_id: str, old: State | None, new: State) -> Signal | None:
    if _edge(old, new, STATE_OFF, STATE_ON):
        return Signal(SignalKind.DOOR_OPEN, new.last_changed, entity_id)
    if _edge(old, new, STATE_ON, STATE_OFF):
        return Signal(SignalKind.DOOR_CLOSE, new.last_changed, entity_id)
    return None


def _presence(entity_id: str, old: State | None, new: State) -> Signal | None:
    if _edge(old, new, STATE_OFF, STATE_ON):
        return Signal(SignalKind.PRESENCE_ON, new.last_changed, entity_id)
    if _edge(old, new, STATE_ON, STATE_OFF):
        return Signal(SignalKind.PRESENCE_OFF, new.last_changed, entity_id)
    return None


def _resident(entity_id: str, old: State | None, new: State) -> Signal | None:
    if entity_id.startswith("event."):
        return _event(SignalKind.RESIDENT, entity_id, old, new)
    if _changed(old, new) and new.state in RESIDENT_STATES:
        return Signal(SignalKind.RESIDENT, new.last_changed, entity_id, new.state)
    return None


def _lock(entity_id: str, old: State | None, new: State) -> Signal | None:
    if _changed(old, new):
        return Signal(SignalKind.LOCK, new.last_changed, entity_id, new.state)
    return None


def _guest_phone(guest_id: str, entity_id: str, last_known: str | None, new: State) -> Signal | None:
    """Compare `home` with the last real state of the tracker (`unavailable` and `unknown` in between don't count).

    Nothing known yet (`last_known` None) counts as away for a phone that turns up at home. A phone that goes away
    from there leaves a signal too, because a restored visit may still have it as home; the engine drops it when it
    has no home signal for the phone.
    """
    if new.state in STATE_IGNORED or new.state == last_known:
        return None
    if new.state == STATE_HOME:
        return Signal(SignalKind.GUEST_HOME, new.last_changed, entity_id, new.state, guest_id)
    if last_known is None or last_known == STATE_HOME:
        return Signal(SignalKind.GUEST_AWAY, new.last_changed, entity_id, new.state, guest_id)
    return None


SOURCE_CONVERTERS: tuple[tuple[str, Converter], ...] = (
    (CONF_DOORBELLS, _doorbell),
    (CONF_DOORS, _door),
    (CONF_PRESENCE, _presence),
    (CONF_LOCKS, _lock),
    (CONF_RESIDENT_SIGNALS, _resident),
)


class SignalAdapter:
    def __init__(
        self,
        hass: HomeAssistant,
        config: Mapping[str, Any],
        guests: list[Guest],
        on_signal: Callable[[Signal], None],
    ) -> None:
        self._hass = hass
        self._on_signal = on_signal
        self._trackers: dict[str, str] = {}
        self._last_known: dict[str, str] = {}  # last real state (not unavailable/unknown) per tracker
        self._unsub_trackers: CALLBACK_TYPE | None = None
        self._converters: dict[str, list[Converter]] = {}
        self._unsub_sources: CALLBACK_TYPE | None = None
        self._set_sources(config)
        self._set_trackers(guests)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        self._subscribe_sources()
        self._subscribe_trackers()

        @callback
        def stop() -> None:
            self._unsubscribe_sources()
            self._unsubscribe_trackers()

        return stop

    @callback
    def async_set_sources(self, config: Mapping[str, Any]) -> None:
        """Listen to the sources of `config` instead of the old ones; the entities need not exist."""
        self._unsubscribe_sources()
        self._set_sources(config)
        self._subscribe_sources()

    def _set_sources(self, config: Mapping[str, Any]) -> None:
        self._converters = {}
        for key, converter in SOURCE_CONVERTERS:
            for entity_id in config.get(key, []):
                self._converters.setdefault(entity_id, []).append(converter)

    def _subscribe_sources(self) -> None:
        self._unsub_sources = async_track_state_change_event(
            self._hass, list(self._converters), self._handle_state_change
        )

    def _unsubscribe_sources(self) -> None:
        if self._unsub_sources:
            self._unsub_sources()
            self._unsub_sources = None

    @callback
    def async_set_guests(self, guests: list[Guest]) -> None:
        self._unsubscribe_trackers()
        self._set_trackers(guests)
        self._subscribe_trackers()

    def _set_trackers(self, guests: list[Guest]) -> None:
        self._trackers = {tracker: guest.id for guest in guests for tracker in guest.trackers}
        self._last_known = {
            tracker: state.state
            for tracker in self._trackers
            if (state := self._hass.states.get(tracker)) is not None and state.state not in STATE_IGNORED
        } | {tracker: known for tracker, known in self._last_known.items() if tracker in self._trackers}

    def _subscribe_trackers(self) -> None:
        if self._trackers:
            self._unsub_trackers = async_track_state_change_event(
                self._hass, list(self._trackers), self._handle_tracker_change
            )

    def _unsubscribe_trackers(self) -> None:
        if self._unsub_trackers:
            self._unsub_trackers()
            self._unsub_trackers = None

    @callback
    def _handle_tracker_change(self, event: Event[EventStateChangedData]) -> None:
        new = event.data["new_state"]
        if new is None or (guest_id := self._trackers.get(new.entity_id)) is None or new.state in STATE_IGNORED:
            return
        last_known = self._last_known.get(new.entity_id)
        self._last_known[new.entity_id] = new.state
        if signal := _guest_phone(guest_id, new.entity_id, last_known, new):
            self._on_signal(signal)

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        for converter in self._converters.get(new.entity_id, []):
            if signal := converter(new.entity_id, old, new):
                self._on_signal(signal)
