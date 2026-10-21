"""Guestbook: turns doorbell, door and presence signals into a log of visits."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant

from .adapter import SignalAdapter
from .core import Engine, Settings
from .runtime import GuestbookRuntime
from .store import GuestbookStore

PLATFORMS = [Platform.CALENDAR]

type GuestbookConfigEntry = ConfigEntry[GuestbookRuntime]


async def async_setup_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    store = GuestbookStore(hass)
    await store.async_load()
    runtime = GuestbookRuntime(hass, store, Engine(Settings(), guests=[], entries=store.entries))
    entry.runtime_data = runtime
    runtime.async_start()
    entry.async_on_unload(SignalAdapter(hass, entry.data, runtime.async_handle_signal).async_start())
    entry.async_on_unload(runtime.async_stop)
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: GuestbookConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
