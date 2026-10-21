"""Visits calendar."""

from __future__ import annotations

from datetime import datetime

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GuestbookConfigEntry
from .const import DOMAIN
from .core import Certainty, Entry
from .runtime import GuestbookRuntime


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VisitsCalendar(entry)])


class VisitsCalendar(CalendarEntity):
    _attr_has_entity_name = True
    _attr_should_poll = False
    _attr_translation_key = "visits"

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        self._runtime: GuestbookRuntime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_visits"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Guestbook", entry_type=DeviceEntryType.SERVICE
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._runtime.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()

    @property
    def event(self) -> CalendarEvent | None:
        """Return the latest open visit."""
        now = dt_util.utcnow()
        open_visits = [e for e in self._runtime.async_visits() if e.open]
        return _to_event(max(open_visits, key=lambda e: e.start), now) if open_visits else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        now = dt_util.utcnow()
        events = (_to_event(entry, now) for entry in self._runtime.async_visits())
        return sorted((e for e in events if e.start < end_date and e.end > start_date), key=lambda e: e.start)


def _to_event(entry: Entry, now: datetime) -> CalendarEvent:
    summary = "Visit (uncertain)" if entry.certainty is Certainty.UNCERTAIN else "Visit"
    return CalendarEvent(
        start=entry.start,
        end=entry.end or max(now, entry.start),
        summary=summary,
        description=entry.reason.detail if entry.reason else None,
        uid=entry.id,
    )
