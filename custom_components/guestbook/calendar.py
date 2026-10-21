"""Visits calendar."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GuestbookConfigEntry
from .core import Certainty, Entry, EntryKind
from .entity import GuestbookEntity

OPEN_ENTRY_MARGIN = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VisitsCalendar(entry), RingsCalendar(entry)])


class GuestbookCalendar(GuestbookEntity, CalendarEntity):
    entry_kind: EntryKind
    unique_suffix: str

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        super().__init__(entry, self.unique_suffix)
        self._attr_translation_key = self.unique_suffix

    @property
    def event(self) -> CalendarEvent | None:
        """Return the latest open or ongoing entry."""
        now = dt_util.utcnow()
        current = [e for e in self._runtime.async_entries(self.entry_kind) if e.open or e.start <= now < e.end]
        if not current:
            return None
        latest = max(current, key=lambda e: e.start)
        event = self._to_event(latest, now)
        # The calendar state is "on" only before the event end; an open entry has no end yet.
        return replace(event, end=event.end + OPEN_ENTRY_MARGIN) if latest.open else event

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        now = dt_util.utcnow()
        events = (self._to_event(entry, now) for entry in self._runtime.async_entries(self.entry_kind))
        return sorted((e for e in events if e.start < end_date and e.end > start_date), key=lambda e: e.start)

    def _to_event(self, entry: Entry, now: datetime) -> CalendarEvent:
        return CalendarEvent(
            start=entry.start,
            end=entry.end or max(now, entry.start),
            summary=self._summary(entry),
            description=entry.reason.detail if entry.reason else None,
            uid=entry.id,
        )

    def _summary(self, entry: Entry) -> str:
        raise NotImplementedError


class VisitsCalendar(GuestbookCalendar):
    entry_kind = EntryKind.VISIT
    unique_suffix = "visits"

    def _summary(self, entry: Entry) -> str:
        if entry.guests:
            return "Visit: " + ", ".join(guest["name"] for guest in entry.guests)
        return "Visit (uncertain)" if entry.certainty is Certainty.UNCERTAIN else "Visit"


class RingsCalendar(GuestbookCalendar):
    entry_kind = EntryKind.UNANSWERED_RING
    unique_suffix = "rings"

    def _summary(self, entry: Entry) -> str:
        return "Unanswered ring"
