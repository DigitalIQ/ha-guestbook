"""Persistence of entries."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store

from .const import SAVE_DELAY, STORAGE_KEY, STORAGE_VERSION
from .core import Entry


class GuestbookStore:
    def __init__(self, hass: HomeAssistant) -> None:
        self._store: Store[dict[str, Any]] = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._entries: dict[str, Entry] = {}

    @property
    def entries(self) -> list[Entry]:
        return list(self._entries.values())

    async def async_load(self) -> None:
        data = await self._store.async_load()
        self._entries = {e.id: e for e in (Entry.from_dict(item) for item in (data or {}).get("entries", []))}

    @callback
    def async_put(self, entry: Entry) -> None:
        self._entries[entry.id] = entry
        self._store.async_delay_save(self._data, SAVE_DELAY.total_seconds())

    @callback
    def async_remove(self, entry_id: str) -> None:
        if self._entries.pop(entry_id, None) is not None:
            self._store.async_delay_save(self._data, SAVE_DELAY.total_seconds())

    async def async_flush(self) -> None:
        await self._store.async_save(self._data())

    def _data(self) -> dict[str, Any]:
        return {"entries": [entry.to_dict() for entry in self._entries.values()]}


async def async_remove_stored_entries(hass: HomeAssistant) -> None:
    """Delete the storage file of the entries (used when the integration is removed)."""
    await Store(hass, STORAGE_VERSION, STORAGE_KEY).async_remove()
