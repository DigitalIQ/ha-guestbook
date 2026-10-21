from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_fire_time_changed

from custom_components.guestbook.const import (
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_PRESENCE,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
    DOMAIN,
)

DOORBELL = "event.front_doorbell"
DOOR = "binary_sensor.front_door"
PRESENCE = "binary_sensor.hall_presence"


@pytest.fixture
def config_entry() -> MockConfigEntry:
    return MockConfigEntry(
        domain=DOMAIN,
        title="Guestbook",
        data={
            CONF_DOORBELLS: [DOORBELL],
            CONF_DOORS: [DOOR],
            CONF_PRESENCE: [PRESENCE],
            CONF_RESIDENTS: [],
            CONF_RESIDENT_SIGNALS: [],
        },
    )


@pytest.fixture
async def setup_guestbook(hass: HomeAssistant, config_entry: MockConfigEntry, freezer) -> MockConfigEntry:
    freezer.move_to("2026-10-21 14:00:00+00:00")
    hass.states.async_set(DOORBELL, "unknown")
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(PRESENCE, "off")
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


async def get_visits(hass: HomeAssistant) -> list[dict]:
    now = dt_util.utcnow()
    response = await hass.services.async_call(
        "calendar",
        "get_events",
        {
            "entity_id": "calendar.guestbook_visits",
            "start_date_time": (now - timedelta(days=1)).isoformat(),
            "end_date_time": (now + timedelta(days=1)).isoformat(),
        },
        blocking=True,
        return_response=True,
    )
    return response["calendar.guestbook_visits"]["events"]
