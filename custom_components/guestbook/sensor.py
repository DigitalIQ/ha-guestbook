"""Sensor: the current visit."""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GuestbookConfigEntry
from .core import Entry, effective_guests, unknown_guest
from .entity import GuestbookEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([CurrentVisitSensor(entry)])


class CurrentVisitSensor(GuestbookEntity, SensorEntity):
    _attr_translation_key = "current_visit"

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        super().__init__(entry, "current_visit")

    @property
    def _visit(self) -> Entry | None:
        return next(iter(self._runtime.async_open_visits()), None)

    @property
    def native_value(self) -> str | None:
        if (visit := self._visit) is None:
            return None
        return ", ".join(effective_guests(visit)) or unknown_guest(self.hass.config.language)

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if (visit := self._visit) is None:
            return None
        return {
            "entry_id": visit.id,
            "start": visit.start.isoformat(),
            "certainty": visit.certainty.value if visit.certainty else None,
        }
