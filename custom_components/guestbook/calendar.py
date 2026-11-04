"""Visits calendar."""

from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEntityFeature, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.util import dt as dt_util

from . import GuestbookConfigEntry
from .const import DOMAIN
from .core import EffectiveKind, Entry, effective_end, effective_start, plan_edit, render_description, render_title
from .entity import GuestbookEntity

OPEN_ENTRY_MARGIN = timedelta(minutes=1)


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VisitsCalendar(entry), RingsCalendar(entry)])


class GuestbookCalendar(GuestbookEntity, CalendarEntity):
    entry_kinds: tuple[EffectiveKind, ...]
    unique_suffix: str
    _attr_supported_features = CalendarEntityFeature.UPDATE_EVENT | CalendarEntityFeature.DELETE_EVENT

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        super().__init__(entry, self.unique_suffix)
        self._attr_translation_key = self.unique_suffix

    @property
    def event(self) -> CalendarEvent | None:
        """Return the latest open or ongoing entry."""
        now = dt_util.utcnow()
        current = [
            e
            for e in self._runtime.async_entries(*self.entry_kinds)
            if (end := effective_end(e)) is None or effective_start(e) <= now < end
        ]
        if not current:
            return None
        latest = max(current, key=effective_start)
        event = self._to_event(latest, now)
        # The calendar state is "on" only before the event end; an open entry has no end yet.
        return replace(event, end=event.end + OPEN_ENTRY_MARGIN) if effective_end(latest) is None else event

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        now = dt_util.utcnow()
        events = (self._to_event(entry, now) for entry in self._runtime.async_entries(*self.entry_kinds))
        return sorted((e for e in events if e.start < end_date and e.end > start_date), key=lambda e: e.start)

    async def async_update_event(
        self,
        uid: str,
        event: dict[str, Any],
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Edit an entry from the calendar dialog. See `GuestbookRuntime.async_edit_entry` for what edits mean."""
        entry = self._runtime.async_calendar_entry(uid, self.entry_kinds)
        start, end = event["dtstart"], event["dtend"]
        if recurrence_id or event.get("rrule"):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="calendar_repeat")
        if not (isinstance(start, datetime) and isinstance(end, datetime)):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="calendar_all_day")
        if not event["summary"].strip():
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="calendar_empty_title")
        plan = plan_edit(
            entry,
            summary=event["summary"],
            start=dt_util.as_utc(start),
            end=dt_util.as_utc(end),
            generated=self._description(entry, self.hass.config.language),
            sent=event.get("description"),
        )
        self._runtime.async_edit_entry(entry, plan)

    async def async_delete_event(
        self,
        uid: str,
        recurrence_id: str | None = None,
        recurrence_range: str | None = None,
    ) -> None:
        """Delete from the calendar dialog hides the entry; it stays stored and in the export."""
        self._runtime.async_hide_entry(self._runtime.async_calendar_entry(uid, self.entry_kinds))

    def _to_event(self, entry: Entry, now: datetime) -> CalendarEvent:
        language = self.hass.config.language
        return CalendarEvent(
            start=effective_start(entry),
            end=effective_end(entry) or max(now, effective_start(entry)),
            summary=render_title(entry, language),
            description=self._description(entry, language) or None,
            uid=entry.id,
        )

    def _description(self, entry: Entry, language: str) -> str:
        names = {}
        for signal in entry.signals:
            if signal.source not in names and (state := self.hass.states.get(signal.source)) is not None:
                names[signal.source] = state.name
        return render_description(entry, language, names, dt_util.get_default_time_zone())


class VisitsCalendar(GuestbookCalendar):
    entry_kinds = (EffectiveKind.VISIT,)
    unique_suffix = "visits"


class RingsCalendar(GuestbookCalendar):
    entry_kinds = (EffectiveKind.UNANSWERED_RING, EffectiveKind.DELIVERY)
    unique_suffix = "rings"
