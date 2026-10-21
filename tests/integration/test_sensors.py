from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.guestbook.const import DOMAIN

from .conftest import (
    ALEX_PHONE,
    DOOR,
    SAM_PHONE,
    add_guest,
    advance,
    ring,
    set_tracker,
)

VISIT_ACTIVE = "binary_sensor.guestbook_visit_active"
CURRENT_VISIT = "sensor.guestbook_current_visit"
ALEX = "binary_sensor.alex_visiting"
SAM = "binary_sensor.sam_visiting"


async def start_uncertain_visit(hass: HomeAssistant) -> None:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()


async def test_no_visit_means_inactive_and_no_current_visit(hass: HomeAssistant, setup_guestbook):
    assert hass.states.get(VISIT_ACTIVE).state == "off"
    current = hass.states.get(CURRENT_VISIT)
    assert current.state == "unknown"
    assert "entry_id" not in current.attributes


async def test_visit_active_follows_an_uncertain_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await start_uncertain_visit(hass)
    assert hass.states.get(VISIT_ACTIVE).state == "on"

    await advance(hass, freezer, timedelta(hours=4))

    assert hass.states.get(VISIT_ACTIVE).state == "off"


async def test_current_visit_of_an_uncertain_visit_has_no_guest(hass: HomeAssistant, setup_guestbook, freezer):
    await advance(hass, freezer, timedelta(minutes=1))
    await start_uncertain_visit(hass)

    current = hass.states.get(CURRENT_VISIT)

    assert current.state == "unknown"
    assert set(current.attributes) - {"friendly_name"} == {"entry_id", "start", "certainty"}
    assert current.attributes["certainty"] == "uncertain"
    assert current.attributes["start"] == "2026-10-21T14:01:00+00:00"
    assert current.attributes["entry_id"]


async def test_current_visit_lists_the_guest_names(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await add_guest(hass, setup_guestbook, "Sam", [SAM_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")
    assert hass.states.get(CURRENT_VISIT).state == "Alex"
    assert hass.states.get(CURRENT_VISIT).attributes["certainty"] == "certain"
    await set_tracker(hass, SAM_PHONE, "home")

    assert hass.states.get(CURRENT_VISIT).state == "Alex, Sam"


async def test_current_visit_clears_when_the_visit_ends(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await set_tracker(hass, ALEX_PHONE, "not_home")

    await advance(hass, freezer, timedelta(minutes=5))

    assert hass.states.get(VISIT_ACTIVE).state == "off"
    assert "entry_id" not in hass.states.get(CURRENT_VISIT).attributes


async def test_each_guest_gets_a_binary_sensor_on_while_visiting(hass: HomeAssistant, setup_guestbook, freezer):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await add_guest(hass, setup_guestbook, "Sam", [SAM_PHONE])
    assert hass.states.get(ALEX).state == "off"
    assert hass.states.get(SAM).state == "off"
    entry = er.async_get(hass).async_get(ALEX)
    assert entry.config_subentry_id == subentry_id

    await set_tracker(hass, ALEX_PHONE, "home")

    assert hass.states.get(ALEX).state == "on"
    assert hass.states.get(SAM).state == "off"
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))
    assert hass.states.get(ALEX).state == "off"


async def test_guest_sensor_is_on_when_the_guest_joined_an_uncertain_visit(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await start_uncertain_visit(hass)
    assert hass.states.get(ALEX).state == "off"

    await set_tracker(hass, ALEX_PHONE, "home")

    assert hass.states.get(ALEX).state == "on"


async def test_guest_sensor_disappears_with_the_guest(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    assert hass.states.get(ALEX) is not None
    devices = dr.async_get(hass)
    assert devices.async_get_device_by_identifier((DOMAIN, subentry_id), setup_guestbook.entry_id) is not None

    hass.config_entries.async_remove_subentry(setup_guestbook, subentry_id)
    await hass.async_block_till_done()

    assert hass.states.get(ALEX) is None
    assert er.async_get(hass).async_get(ALEX) is None
    assert dr.async_get(hass).async_get_device_by_identifier((DOMAIN, subentry_id), setup_guestbook.entry_id) is None
    assert hass.states.get(VISIT_ACTIVE) is not None


async def test_renamed_guest_updates_the_sensor_name(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "reconfigure", "subentry_id": subentry_id}
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Alexandra", "trackers": [ALEX_PHONE]}
    )
    await hass.async_block_till_done()

    assert hass.states.get(ALEX).attributes["friendly_name"] == "Alexandra Visiting"


async def test_sensors_are_right_after_a_restart_with_an_open_visit(hass: HomeAssistant, setup_guestbook):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(VISIT_ACTIVE).state == "on"
    assert hass.states.get(CURRENT_VISIT).state == "Alex"
    assert hass.states.get(ALEX).state == "on"
