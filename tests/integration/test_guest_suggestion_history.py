"""The phone preselection reads the recorder history, so this module runs with an in-memory recorder."""

from datetime import timedelta

import pytest
from homeassistant.components.repairs import DOMAIN as REPAIRS_DOMAIN
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.components.recorder.common import async_wait_recording_done

from custom_components.guestbook.const import DOMAIN

from .conftest import DOOR, advance, ring

ROBIN_PHONE = "device_tracker.robin_phone"
NEIGHBOUR_PHONE = "device_tracker.neighbour_phone"


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(recorder_mock, enable_custom_integrations):
    """The recorder has to exist before the hass fixture is used, so it is requested first."""


async def test_preselection_uses_the_recorder_history_of_the_visit(hass: HomeAssistant, setup_guestbook, freezer):
    assert await async_setup_component(hass, "repairs", {})
    flows = hass.data[REPAIRS_DOMAIN]["flow_manager"]
    hass.states.async_set(ROBIN_PHONE, "not_home")
    hass.states.async_set(NEIGHBOUR_PHONE, "not_home")
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    entry_id = hass.states.get("sensor.guestbook_current_visit").attributes["entry_id"]
    await advance(hass, freezer, timedelta(minutes=10))
    hass.states.async_set(ROBIN_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=20))
    hass.states.async_set(ROBIN_PHONE, "not_home")
    await advance(hass, freezer, timedelta(hours=4))
    hass.states.async_set(NEIGHBOUR_PHONE, "home")
    await async_wait_recording_done(hass)
    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": "visit", "guest_name": "Robin"}, blocking=True
    )

    result = await flows.async_init(DOMAIN, context={"issue_id": "guest_suggestion_robin"})

    (key,) = result["data_schema"].schema
    assert key.description["suggested_value"] == [ROBIN_PHONE]
