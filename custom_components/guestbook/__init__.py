"""Guestbook: turns doorbell, door and presence signals into a log of visits."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.typing import ConfigType

from .adapter import SignalAdapter
from .const import CONF_NAME, CONF_TRACKERS, DOMAIN, SUBENTRY_GUEST
from .core import Engine, Guest
from .notifier import Notifier
from .runtime import GuestbookRuntime
from .services import async_register_services
from .settings import settings_from_options
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
    runtime = GuestbookRuntime(
        hass, store, Engine(settings_from_options(entry.options), guests=guests, entries=store.entries), guests
    )
    adapter = SignalAdapter(hass, entry.data, guests, runtime.async_handle_signal)
    entry.runtime_data = runtime
    known_guests = guests
    known_settings = runtime.settings

    async def async_entry_updated(hass: HomeAssistant, entry: ConfigEntry) -> None:
        nonlocal known_guests, known_settings
        if (settings := settings_from_options(entry.options)) != known_settings:
            known_settings = settings
            runtime.async_set_settings(settings)
        if (guests := _guests(entry)) != known_guests:
            known_guests = guests
            adapter.async_set_guests(guests)
            runtime.async_set_guests(guests)

    entry.async_on_unload(Notifier(hass, entry, runtime).async_start())

    runtime.async_start()
    entry.async_on_unload(adapter.async_start())
    entry.async_on_unload(entry.add_update_listener(async_entry_updated))
    entry.async_on_unload(runtime.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
