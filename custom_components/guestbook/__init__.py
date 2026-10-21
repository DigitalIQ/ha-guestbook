"""Guestbook: turns doorbell, door and presence signals into a log of visits."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .adapter import SignalAdapter
from .const import DOMAIN, SOURCE_KEYS
from .core import Engine
from .guests import guests_of
from .notifier import Notifier
from .repairs import GuestSuggestions, SourceMonitor, async_delete_issues
from .runtime import GuestbookRuntime
from .services import async_register_services
from .settings import settings_from_options
from .store import GuestbookStore, async_remove_stored_entries

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type GuestbookConfigEntry = ConfigEntry[GuestbookRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


def _sources(entry: ConfigEntry) -> dict[str, list[str]]:
    return {key: list(entry.data.get(key, [])) for key in SOURCE_KEYS}


async def async_setup_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    store = GuestbookStore(hass)
    await store.async_load()
    guests = guests_of(entry)
    runtime = GuestbookRuntime(
        hass, store, Engine(settings_from_options(entry.options), guests=guests, entries=store.entries), guests
    )
    adapter = SignalAdapter(hass, entry.data, guests, runtime.async_handle_signal)
    entry.runtime_data = runtime
    monitor = SourceMonitor(hass, entry)
    suggestions = GuestSuggestions(hass, entry, lambda visit_id: runtime.async_get_entry(visit_id) is not None)
    known_guests = guests
    known_settings = runtime.settings
    known_sources = _sources(entry)

    async def async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        nonlocal known_guests, known_settings, known_sources
        if (settings := settings_from_options(entry.options)) != known_settings:
            known_settings = settings
            runtime.async_set_settings(settings)
        if (sources := _sources(entry)) != known_sources:
            known_sources = sources
            adapter.async_set_sources(entry.data)
            monitor.async_refresh()
        if (guests := guests_of(entry)) != known_guests:
            known_guests = guests
            adapter.async_set_guests(guests)
            runtime.async_set_guests(guests)
            suggestions.async_cleanup()

    entry.async_on_unload(Notifier(hass, entry, runtime).async_start())
    entry.async_on_unload(runtime.async_add_purge_listener(suggestions.async_cleanup))

    runtime.async_start()
    entry.async_on_unload(adapter.async_start())
    entry.async_on_unload(monitor.async_start())
    entry.async_on_unload(suggestions.async_start())
    entry.async_on_unload(entry.add_update_listener(async_entry_updated))
    entry.async_on_unload(runtime.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    async_delete_issues(hass)
    await async_remove_stored_entries(hass)
