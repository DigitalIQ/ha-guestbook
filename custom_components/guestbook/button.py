"""Buttons that correct the latest entry."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GuestbookConfigEntry
from .core import CorrectionKind
from .entity import GuestbookEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([CorrectionButton(entry, kind) for kind in CorrectionKind])


class CorrectionButton(GuestbookEntity, ButtonEntity):
    """One button per correction kind. A press corrects the latest entry with the source `button`."""

    def __init__(self, entry: GuestbookConfigEntry, kind: CorrectionKind) -> None:
        super().__init__(entry, f"correct_{kind.value}")
        self._attr_translation_key = kind.value
        self._kind = kind

    async def async_press(self) -> None:
        self._runtime.async_press_button(self._kind)
