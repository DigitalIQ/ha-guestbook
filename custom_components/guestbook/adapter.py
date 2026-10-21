"""Turns state changes of the selected source entities into signals."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any

from homeassistant.const import STATE_OFF, STATE_ON, STATE_UNAVAILABLE
from homeassistant.core import CALLBACK_TYPE, Event, EventStateChangedData, HomeAssistant, State, callback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import dt as dt_util

from .const import CONF_DOORBELLS, CONF_DOORS, CONF_PRESENCE
from .core import Signal, SignalKind

type Converter = Callable[[str, State | None, State], Signal | None]


def _edge(old: State | None, new: State, before: str, after: str) -> bool:
    return old is not None and old.state == before and new.state == after


def _doorbell(entity_id: str, old: State | None, new: State) -> Signal | None:
    if entity_id.startswith("event."):
        # An event entity is "unknown" until its first event, so unknown -> timestamp is a real ring.
        if old is None or old.state == STATE_UNAVAILABLE or new.state == old.state:
            return None
        if dt_util.parse_datetime(new.state) is None:
            return None
        return Signal(SignalKind.RING, new.last_changed, entity_id)
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


class SignalAdapter:
    def __init__(self, hass: HomeAssistant, config: Mapping[str, Any], on_signal: Callable[[Signal], None]) -> None:
        self._hass = hass
        self._on_signal = on_signal
        self._converters: dict[str, list[Converter]] = {}
        for key, converter in (
            (CONF_DOORBELLS, _doorbell),
            (CONF_DOORS, _door),
            (CONF_PRESENCE, _presence),
        ):
            for entity_id in config.get(key, []):
                self._converters.setdefault(entity_id, []).append(converter)

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        return async_track_state_change_event(self._hass, list(self._converters), self._handle_state_change)

    @callback
    def _handle_state_change(self, event: Event[EventStateChangedData]) -> None:
        old, new = event.data["old_state"], event.data["new_state"]
        if new is None:
            return
        for converter in self._converters.get(new.entity_id, []):
            if signal := converter(new.entity_id, old, new):
                self._on_signal(signal)
