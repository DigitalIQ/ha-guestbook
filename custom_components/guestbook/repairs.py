"""Repair issues."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import datetime
from types import MappingProxyType
from typing import Any

import probatio
from homeassistant.components.repairs import RepairsFlow
from homeassistant.config_entries import ConfigEntry, ConfigEntryState, ConfigSubentry
from homeassistant.const import EVENT_STATE_CHANGED, STATE_HOME
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers import selector
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started
from homeassistant.util import dt as dt_util

from .const import (
    CONF_NAME,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
    CONF_TRACKERS,
    DOMAIN,
    EVENT_VISIT_CORRECTED,
    SOURCE_KEYS,
    SUBENTRY_GUEST,
)
from .core import effective_end, effective_start
from .guests import guests_of

_LOGGER = logging.getLogger(__name__)

MISSING_SOURCE = "missing_source"
GUEST_SUGGESTION = "guest_suggestion"


def source_entities(config: Mapping[str, Any]) -> set[str]:
    return {entity_id for key in SOURCE_KEYS for entity_id in config.get(key, [])}


class SourceMonitor:
    """Keeps one repair issue per selected source entity that exists nowhere.

    An entity exists when it has a state or an entity registry entry. The first check waits for Home Assistant to
    have started, so entities of integrations that load later do not raise issues.
    """

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry
        self._ready = False
        self._unsubs: list[CALLBACK_TYPE] = []

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        unsub_started = async_at_started(self._hass, self._started)

        @callback
        def stop() -> None:
            if unsub_started:
                unsub_started()
            self._unsubscribe()
            self._ready = False
            self._delete_issues(keep=set())

        return stop

    @callback
    def async_refresh(self) -> None:
        """The selected sources changed: listen to the new ones and check again."""
        if self._ready:
            self._subscribe()
            self._check()

    @callback
    def _started(self, hass: HomeAssistant) -> None:
        self._ready = True
        self.async_refresh()

    @callback
    def _subscribe(self) -> None:
        self._unsubscribe()
        sources = list(source_entities(self._entry.data))
        self._unsubs = [
            async_track_state_change_event(self._hass, sources, self._handle_change),
            self._hass.bus.async_listen(er.EVENT_ENTITY_REGISTRY_UPDATED, self._handle_change, self._registry_filter),
        ]

    @callback
    def _unsubscribe(self) -> None:
        while self._unsubs:
            self._unsubs.pop()()

    @callback
    def _registry_filter(self, data: Mapping[str, Any]) -> bool:
        sources = source_entities(self._entry.data)
        return data.get("entity_id") in sources or data.get("old_entity_id") in sources

    @callback
    def _handle_change(self, event: Event) -> None:
        if event.event_type == EVENT_STATE_CHANGED and None not in (event.data["old_state"], event.data["new_state"]):
            return  # the entity exists before and after, nothing to re-check
        self._check()

    @callback
    def _check(self) -> None:
        registry = er.async_get(self._hass)
        missing = {
            entity_id
            for entity_id in source_entities(self._entry.data)
            if self._hass.states.get(entity_id) is None and registry.async_get(entity_id) is None
        }
        for entity_id in missing:
            ir.async_create_issue(
                self._hass,
                DOMAIN,
                f"{MISSING_SOURCE}_{entity_id}",
                is_fixable=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=MISSING_SOURCE,
                translation_placeholders={"entity_id": entity_id},
            )
        self._delete_issues(keep={f"{MISSING_SOURCE}_{entity_id}" for entity_id in missing})

    @callback
    def _delete_issues(self, keep: set[str]) -> None:
        for domain, issue_id in list(ir.async_get(self._hass).issues):
            if domain == DOMAIN and issue_id.startswith(f"{MISSING_SOURCE}_") and issue_id not in keep:
                ir.async_delete_issue(self._hass, DOMAIN, issue_id)


class GuestSuggestions:
    """Offers to create a guest profile when a correction names a visitor who has none."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self._hass = hass
        self._entry = entry

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        self.async_cleanup()
        return self._hass.bus.async_listen(EVENT_VISIT_CORRECTED, self._handle_correction)

    @callback
    def async_cleanup(self) -> None:
        """Delete the suggestions of this entry for names that have a guest profile now."""
        names = self._guest_names()
        for (domain, issue_id), found in list(ir.async_get(self._hass).issues.items()):
            data = found.data or {}
            if (
                domain == DOMAIN
                and issue_id.startswith(f"{GUEST_SUGGESTION}_")
                and data.get("entry_id") == self._entry.entry_id
                and str(data.get("name", "")).strip().casefold() in names
            ):
                ir.async_delete_issue(self._hass, DOMAIN, issue_id)

    @callback
    def _handle_correction(self, event: Event) -> None:
        name = str(event.data.get("guest_name") or "").strip()
        if event.data.get("kind") != "visit" or not name or name.casefold() in self._guest_names():
            return
        ir.async_create_issue(
            self._hass,
            DOMAIN,
            f"{GUEST_SUGGESTION}_{name.casefold()}",
            data={"entry_id": self._entry.entry_id, "name": name, "visit_id": event.data["entry_id"]},
            is_fixable=True,
            is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key=GUEST_SUGGESTION,
            translation_placeholders={"name": name},
        )

    def _guest_names(self) -> set[str]:
        return {guest.name.strip().casefold() for guest in guests_of(self._entry)}


@callback
def async_delete_issues(hass: HomeAssistant) -> None:
    """Delete every issue of Guestbook (the entry was removed)."""
    for domain, issue_id in list(ir.async_get(hass).issues):
        if domain == DOMAIN:
            ir.async_delete_issue(hass, DOMAIN, issue_id)


async def async_suggested_trackers(hass: HomeAssistant, entry: ConfigEntry, visit_id: str | None) -> list[str]:
    """Device trackers that were home during the visit and belong to no guest and no resident.

    The history comes from the recorder when it is loaded. Without it, or without the visit, the trackers that are
    home now are used.
    """
    taken = {tracker for guest in guests_of(entry) for tracker in guest.trackers}
    taken.update(_resident_trackers(hass, entry))
    candidates = sorted(t for t in hass.states.async_entity_ids("device_tracker") if t not in taken)
    visit = entry.runtime_data.async_get_entry(visit_id) if visit_id else None
    if visit is not None and candidates and "recorder" in hass.config.components:
        try:
            home = await _async_home_during(hass, candidates, effective_start(visit), effective_end(visit))
        except Exception:
            _LOGGER.warning("Could not read the recorder history, using the current states", exc_info=True)
        else:
            return [t for t in candidates if t in home]
    return [t for t in candidates if hass.states.is_state(t, STATE_HOME)]


def _resident_trackers(hass: HomeAssistant, entry: ConfigEntry) -> set[str]:
    trackers = {e for e in entry.data.get(CONF_RESIDENT_SIGNALS, []) if e.startswith("device_tracker.")}
    for person in entry.data.get(CONF_RESIDENTS, []):
        if (state := hass.states.get(person)) is not None:
            trackers.update(state.attributes.get("device_trackers", []))
    return trackers


async def _async_home_during(
    hass: HomeAssistant, trackers: list[str], start: datetime, end: datetime | None
) -> set[str]:
    from homeassistant.components.recorder import get_instance
    from homeassistant.components.recorder.history import get_significant_states

    states = await get_instance(hass).async_add_executor_job(
        lambda: get_significant_states(
            hass,
            start,
            end or dt_util.utcnow(),
            trackers,
            include_start_time_state=True,
            significant_changes_only=False,
            no_attributes=True,
        )
    )
    return {entity_id for entity_id, history in states.items() if any(s.state == STATE_HOME for s in history)}


class GuestSuggestionFlow(RepairsFlow):
    """Creates the guest of a suggestion; the form shows the name and preselects the phones."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> Any:
        # Home Assistant passes the issue id as `user_input` of the first call.
        return await self.async_step_guest()

    async def async_step_guest(self, user_input: dict[str, Any] | None = None) -> Any:
        data = self.data or {}
        entry = self.hass.config_entries.async_get_entry(str(data.get("entry_id")))
        if entry is None or entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="not_loaded")
        name = str(data["name"])
        if user_input is not None:
            if name.casefold() not in {guest.name.strip().casefold() for guest in guests_of(entry)}:
                self.hass.config_entries.async_add_subentry(
                    entry,
                    ConfigSubentry(
                        data=MappingProxyType(
                            {CONF_NAME: name, CONF_TRACKERS: list(user_input.get(CONF_TRACKERS, []))}
                        ),
                        subentry_type=SUBENTRY_GUEST,
                        title=name,
                        unique_id=None,
                    ),
                )
            return self.async_create_entry(data={})
        schema = probatio.Schema(
            {
                probatio.Optional(CONF_TRACKERS): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker", multiple=True)
                )
            }
        )
        suggested = await async_suggested_trackers(self.hass, entry, data.get("visit_id"))
        return self.async_show_form(
            step_id="guest",
            data_schema=self.add_suggested_values_to_schema(schema, {CONF_TRACKERS: suggested}),
            description_placeholders={"name": name},
        )


async def async_create_fix_flow(hass: HomeAssistant, issue_id: str, data: dict[str, Any] | None) -> RepairsFlow:
    return GuestSuggestionFlow()
