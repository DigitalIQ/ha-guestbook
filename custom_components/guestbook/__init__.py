"""Guestbook: turns doorbell, door and presence signals into a log of visits."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .adapter import SignalAdapter
from .const import CONF_NAME, CONF_TRACKERS, DOMAIN, SUBENTRY_GUEST
from .core import Engine, Guest, Settings
from .runtime import GuestbookRuntime
from .services import async_register_services
from .store import GuestbookStore

PLATFORMS = [Platform.BINARY_SENSOR, Platform.CALENDAR, Platform.SENSOR]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type GuestbookConfigEntry = ConfigEntry[GuestbookRuntime]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    async_register_services(hass)
    return True


def _guests(entry: ConfigEntry) -> list[Guest]:
    return [
        Guest(sub.subentry_id, sub.data[CONF_NAME], list(sub.data.get(CONF_TRACKERS, [])))
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_GUEST
    ]


async def async_setup_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    store = GuestbookStore(hass)
    await store.async_load()
    guests = _guests(entry)
    runtime = GuestbookRuntime(hass, store, Engine(Settings(), guests=guests, entries=store.entries))
    adapter = SignalAdapter(hass, entry.data, guests, runtime.async_handle_signal)
    entry.runtime_data = runtime

    async def async_guests_changed(hass: HomeAssistant, entry: ConfigEntry) -> None:
        guests = _guests(entry)
        adapter.async_set_guests(guests)
        runtime.async_set_guests(guests)

    runtime.async_start()
    entry.async_on_unload(adapter.async_start())
    entry.async_on_unload(entry.add_update_listener(async_guests_changed))
    entry.async_on_unload(runtime.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
