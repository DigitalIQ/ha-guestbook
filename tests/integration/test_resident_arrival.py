import json
from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util

from custom_components.guestbook.const import DOMAIN

from .conftest import (
    DOOR,
    FINGERPRINT,
    LOCK,
    RESIDENT_BUTTON,
    RESIDENT_LOCK,
    RESIDENT_PHONE,
    advance,
    get_visits,
    ring,
)


def stored_entries(hass_storage) -> list[dict]:
    return hass_storage["guestbook.entries"]["data"]["entries"]


async def test_ring_after_a_resident_signal_is_a_resident_arrival(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    hass.states.async_set(RESIDENT_PHONE, "home")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=1))
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    assert stored["kind"] == "resident_arrival"
    assert stored["reason"]["code"] == "resident_signal"
    assert stored["end"] is not None


async def test_resident_signal_after_the_ring_beats_the_door_opening(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    hass.states.async_set(RESIDENT_BUTTON, "on")
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    assert await get_visits(hass) == []


async def test_resident_signal_turns_a_started_visit_into_a_resident_arrival(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert len(await get_visits(hass)) == 1

    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(RESIDENT_LOCK, "unlocked")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []
    assert hass.states.get("calendar.guestbook_visits").state == "off"
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    assert stored["kind"] == "resident_arrival"
    assert [s["kind"] for s in stored["signals"]] == ["ring", "door_open", "resident"]


@pytest.mark.parametrize(
    ("entity_id", "before", "after"),
    [
        (RESIDENT_BUTTON, "off", "on"),
        (RESIDENT_PHONE, "not_home", "home"),
        (RESIDENT_LOCK, "locked", "unlocked"),
    ],
)
async def test_resident_entities_signal_on_a_change_to_on_home_or_unlocked(
    hass: HomeAssistant, setup_guestbook, entity_id, before, after
):
    hass.states.async_set(entity_id, before)
    await hass.async_block_till_done()
    await ring(hass)
    hass.states.async_set(entity_id, after)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


@pytest.mark.parametrize(
    ("entity_id", "start", "end"),
    [
        (RESIDENT_BUTTON, "on", "off"),
        (RESIDENT_PHONE, "home", "not_home"),
        (RESIDENT_LOCK, "unlocked", "locked"),
    ],
)
async def test_resident_entities_do_not_signal_on_the_way_back(
    hass: HomeAssistant, setup_guestbook, freezer, entity_id, start, end
):
    hass.states.async_set(entity_id, start)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))
    await ring(hass)
    hass.states.async_set(entity_id, end)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert len(await get_visits(hass)) == 1


async def test_resident_entity_ignores_unavailable_and_attribute_changes(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    hass.states.async_set(RESIDENT_PHONE, "unavailable")
    hass.states.async_set(RESIDENT_PHONE, "home")
    hass.states.async_set(RESIDENT_BUTTON, "off", {"battery": 80})
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert len(await get_visits(hass)) == 1


async def test_resident_event_entity_signals_on_a_new_timestamp(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    hass.states.async_set(FINGERPRINT, dt_util.utcnow().isoformat())
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_resident_unlock_action_creates_a_resident_signal(hass: HomeAssistant, setup_guestbook, hass_storage):
    await ring(hass)
    await hass.services.async_call(DOMAIN, "resident_unlock", {"source": "garage keypad"}, blocking=True)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    resident = stored["signals"][-1]
    assert (resident["kind"], resident["source"], resident["state"]) == ("resident", "action", "garage keypad")


async def test_resident_unlock_action_works_without_a_source(hass: HomeAssistant, setup_guestbook):
    await hass.services.async_call(DOMAIN, "resident_unlock", {}, blocking=True)
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_resident_unlock_action_needs_a_loaded_entry(hass: HomeAssistant, setup_guestbook):
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    with pytest.raises(ServiceValidationError):
        await hass.services.async_call(DOMAIN, "resident_unlock", {}, blocking=True)


async def test_lock_changes_are_stored_in_the_open_visit(hass: HomeAssistant, setup_guestbook, hass_storage):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    hass.states.async_set(LOCK, "unlocked")
    hass.states.async_set(LOCK, "unavailable")
    hass.states.async_set(LOCK, "locked")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    locks = [(s["source"], s["state"]) for s in stored["signals"] if s["kind"] == "lock"]
    assert locks == [(LOCK, "unlocked")]
    assert json.dumps(stored)


async def test_lock_changes_without_a_visit_are_not_stored(hass: HomeAssistant, setup_guestbook, hass_storage):
    hass.states.async_set(LOCK, "unlocked")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    assert stored_entries(hass_storage) == []
