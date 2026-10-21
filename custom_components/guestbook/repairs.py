"""Repair issues."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers.start import async_at_started

from .const import DOMAIN, SOURCE_KEYS

MISSING_SOURCE = "missing_source"


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
