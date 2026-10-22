"""Text entity: the guest name that the visit button uses."""

from __future__ import annotations

from homeassistant.components.text import TextEntity, TextMode
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import GuestbookConfigEntry
from .const import MAX_GUEST_NAME_INPUT
from .entity import GuestbookEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([GuestNameText(entry)])


class GuestNameText(GuestbookEntity, TextEntity, RestoreEntity):
    """Holds the name for the "Visit" button; empty means a visit without a name. Restored after a restart."""

    _attr_translation_key = "guest_name"
    _attr_mode = TextMode.TEXT
    _attr_native_min = 0
    _attr_native_max = MAX_GUEST_NAME_INPUT

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        super().__init__(entry, "guest_name")

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if last is not None and last.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            self._runtime.async_set_guest_name(last.state)

    @property
    def native_value(self) -> str:
        return self._runtime.guest_name

    async def async_set_value(self, value: str) -> None:
        self._runtime.async_set_guest_name(value)
