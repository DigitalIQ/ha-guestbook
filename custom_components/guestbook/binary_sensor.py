"""Binary sensors: visit active and one per guest."""

from __future__ import annotations

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import GuestbookConfigEntry
from .const import DOMAIN, SUBENTRY_GUEST
from .entity import GuestbookEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: GuestbookConfigEntry, async_add_entities: AddConfigEntryEntitiesCallback
) -> None:
    async_add_entities([VisitActiveSensor(entry)])
    known: dict[str, GuestSensor] = {}
    devices = dr.async_get(hass)

    @callback
    def sync_guests() -> None:
        guests = {s.subentry_id: s for s in entry.subentries.values() if s.subentry_type == SUBENTRY_GUEST}
        for subentry_id in known.keys() - guests.keys():
            del known[subentry_id]
        for subentry_id, subentry in guests.items():
            if subentry_id in known:
                if device := devices.async_get_device_by_identifier((DOMAIN, subentry_id), entry.entry_id):
                    devices.async_update_device(device.id, name=subentry.title)
            else:
                known[subentry_id] = sensor = GuestSensor(entry, subentry)
                async_add_entities([sensor], config_subentry_id=subentry_id)

    async def async_guests_changed(hass: HomeAssistant, entry: GuestbookConfigEntry) -> None:
        sync_guests()

    sync_guests()
    entry.async_on_unload(entry.add_update_listener(async_guests_changed))


class VisitActiveSensor(GuestbookEntity, BinarySensorEntity):
    _attr_translation_key = "visit_active"

    def __init__(self, entry: GuestbookConfigEntry) -> None:
        super().__init__(entry, "visit_active")

    @property
    def is_on(self) -> bool:
        return bool(self._runtime.async_open_visits())


class GuestSensor(GuestbookEntity, BinarySensorEntity):
    _attr_translation_key = "guest"

    def __init__(self, entry: GuestbookConfigEntry, subentry: ConfigSubentry) -> None:
        super().__init__(
            entry,
            f"guest_{subentry.subentry_id}",
            DeviceInfo(
                identifiers={(DOMAIN, subentry.subentry_id)},
                name=subentry.title,
                entry_type=DeviceEntryType.SERVICE,
            ),
        )
        self._guest_id = subentry.subentry_id

    @property
    def is_on(self) -> bool:
        return any(self._guest_id in visit.present_guest_ids for visit in self._runtime.async_open_visits())
