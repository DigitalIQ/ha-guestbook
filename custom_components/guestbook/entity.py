"""Shared base of the Guestbook entities."""

from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity import Entity

from . import GuestbookConfigEntry
from .const import DOMAIN
from .runtime import GuestbookRuntime


class GuestbookEntity(Entity):
    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, entry: GuestbookConfigEntry, unique_suffix: str, device_info: DeviceInfo | None = None) -> None:
        self._runtime: GuestbookRuntime = entry.runtime_data
        self._attr_unique_id = f"{entry.entry_id}_{unique_suffix}"
        self._attr_device_info = device_info or DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)}, name="Guestbook", entry_type=DeviceEntryType.SERVICE
        )

    async def async_added_to_hass(self) -> None:
        self.async_on_remove(self._runtime.async_add_listener(self._handle_update))

    @callback
    def _handle_update(self) -> None:
        self.async_write_ha_state()
