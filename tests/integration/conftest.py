from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.guestbook.const import (
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_LOCKS,
    CONF_PRESENCE,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
    DOMAIN,
)

DOORBELL = "event.front_doorbell"
DOOR = "binary_sensor.front_door"
PRESENCE = "binary_sensor.hall_presence"
LOCK = "lock.front_door_lock"
FINGERPRINT = "event.fingerprint_reader"
RESIDENT_PHONE = "device_tracker.sam_phone"
RESIDENT_BUTTON = "binary_sensor.resident_button"
RESIDENT_LOCK = "lock.back_door_lock"


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Guestbook",
        data={
            CONF_DOORBELLS: [DOORBELL],
            CONF_DOORS: [DOOR],
            CONF_PRESENCE: [PRESENCE],
            CONF_LOCKS: [LOCK],
            CONF_RESIDENTS: [],
            CONF_RESIDENT_SIGNALS: [FINGERPRINT, RESIDENT_PHONE, RESIDENT_BUTTON, RESIDENT_LOCK],
        },
    )


@pytest.fixture
async def setup_guestbook(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> MockConfigEntry:
    freezer.move_to("2026-10-21 14:00:00+00:00")
    hass.states.async_set(DOORBELL, "unknown")
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(PRESENCE, "off")
    hass.states.async_set(LOCK, "locked")
    hass.states.async_set(FINGERPRINT, "unknown")
    hass.states.async_set(RESIDENT_PHONE, "not_home")
    hass.states.async_set(RESIDENT_BUTTON, "off")
    hass.states.async_set(RESIDENT_LOCK, "locked")
    config_entry.add_to_hass(hass)
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()
    return config_entry


async def advance(hass: HomeAssistant, freezer, delta: timedelta) -> None:
    freezer.tick(delta)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def ring(hass: HomeAssistant) -> None:
    hass.states.async_set(DOORBELL, dt_util.utcnow().isoformat())
    await hass.async_block_till_done()


async def get_events(hass: HomeAssistant, entity_id: str) -> list[dict]:
    now = dt_util.utcnow()
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": entity_id,
            "start_date_time": (now - timedelta(days=1)).isoformat(),
            "end_date_time": (now + timedelta(days=1)).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    return response[entity_id]["events"]


async def get_visits(hass: HomeAssistant) -> list[dict]:
    return await get_events(hass, "calendar.guestbook_visits")


async def get_rings(hass: HomeAssistant) -> list[dict]:
    return await get_events(hass, "calendar.guestbook_rings")


ALEX_PHONE = "device_tracker.alex_phone"
ALEX_TABLET = "device_tracker.alex_tablet"
SAM_PHONE = "device_tracker.sam_phone_guest"


async def add_guest(hass: HomeAssistant, entry: MockConfigEntry, name: str, trackers: list[str]) -> str:
    """Add a guest through the subentry flow and return its subentry id."""
    for tracker in trackers:
        if hass.states.get(tracker) is None:
            hass.states.async_set(tracker, "not_home")
    result = await hass.config_entries.subentries.async_init((entry.entry_id, "guest"), context={"source": "user"})
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": name, "trackers": trackers}
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY
    return next(s.subentry_id for s in entry.subentries.values() if s.title == name)


async def set_tracker(hass: HomeAssistant, entity_id: str, state: str) -> None:
    hass.states.async_set(entity_id, state)
    await hass.async_block_till_done()
