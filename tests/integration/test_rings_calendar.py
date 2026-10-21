from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import DOOR, PRESENCE, RESIDENT_BUTTON, advance, get_rings, get_visits, ring


def parse(value: str):
    return dt_util.parse_datetime(value)


async def test_unanswered_ring_shows_as_a_short_event_in_the_rings_calendar(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await ring(hass)
    assert await get_rings(hass) == []

    await advance(hass, freezer, timedelta(minutes=6))
    (event,) = await get_rings(hass)

    assert event["summary"] == "Unanswered ring"
    assert parse(event["start"]) == parse("2026-10-21T14:00:00+00:00")
    assert parse(event["end"]) == parse("2026-10-21T14:01:00+00:00")


async def test_unanswered_ring_never_shows_in_the_visits_calendar(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    assert len(await get_rings(hass)) == 1
    assert await get_visits(hass) == []
    assert hass.states.get("calendar.guestbook_visits").state == "off"


async def test_visits_and_resident_arrivals_never_show_in_the_rings_calendar(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await ring(hass)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))
    hass.states.async_set(RESIDENT_BUTTON, "on")
    await hass.async_block_till_done()
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    assert len(await get_visits(hass)) == 1
    assert await get_rings(hass) == []


async def test_rings_calendar_is_its_own_entity_with_a_name(hass: HomeAssistant, setup_guestbook):
    state = hass.states.get("calendar.guestbook_rings")

    assert state.attributes["friendly_name"] == "Guestbook Rings"


async def test_unanswered_ring_survives_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert len(await get_rings(hass)) == 1


async def test_ring_that_expires_during_downtime_is_unanswered_after_the_restart(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await ring(hass)
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    freezer.tick(timedelta(minutes=10))

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    (event,) = await get_rings(hass)
    assert parse(event["end"]) == parse("2026-10-21T14:01:00+00:00")
