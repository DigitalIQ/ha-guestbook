from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import DOOR, advance, get_visits, ring


async def start_visit(hass: HomeAssistant, freezer) -> None:
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()


async def open_door_again(hass: HomeAssistant) -> None:
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()


def parse(value: str):
    return dt_util.parse_datetime(value)


async def test_visit_ends_when_the_quiet_period_follows_a_door_opening(hass: HomeAssistant, setup_guestbook, freezer):
    await start_visit(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=29))
    await open_door_again(hass)  # 14:30

    await advance(hass, freezer, timedelta(minutes=9, seconds=59))
    (still_open,) = await get_visits(hass)
    await advance(hass, freezer, timedelta(seconds=1))
    await advance(hass, freezer, timedelta(hours=2))
    (ended,) = await get_visits(hass)

    assert parse(still_open["end"]) == dt_util.utcnow() - timedelta(hours=2, seconds=1)
    assert parse(ended["end"]) == parse("2026-10-21T14:30:00+00:00")


async def test_visit_without_a_further_door_opening_ends_at_the_maximum_duration(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await start_visit(hass, freezer)

    await advance(hass, freezer, timedelta(hours=3, minutes=58))
    (open_visit,) = await get_visits(hass)
    await advance(hass, freezer, timedelta(minutes=2))
    await advance(hass, freezer, timedelta(hours=1))
    (ended,) = await get_visits(hass)

    assert parse(open_visit["end"]) == parse("2026-10-21T17:59:00+00:00")
    assert parse(ended["end"]) == parse("2026-10-21T18:00:00+00:00")


async def test_open_visit_ends_correctly_after_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await start_visit(hass, freezer)
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    await advance(hass, freezer, timedelta(minutes=29))
    await open_door_again(hass)  # 14:30
    await advance(hass, freezer, timedelta(minutes=11))
    await advance(hass, freezer, timedelta(hours=1))

    (visit,) = await get_visits(hass)
    assert parse(visit["end"]) == parse("2026-10-21T14:30:00+00:00")


async def test_visit_that_should_have_ended_during_downtime_ends_when_started_again(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await start_visit(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=29))
    await open_door_again(hass)  # 14:30
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    freezer.tick(timedelta(hours=2))

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    (visit,) = await get_visits(hass)
    assert parse(visit["end"]) == parse("2026-10-21T14:30:00+00:00")


async def test_end_reason_is_stored(hass: HomeAssistant, setup_guestbook, freezer, hass_storage):
    await start_visit(hass, freezer)
    await advance(hass, freezer, timedelta(hours=4))

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    (stored,) = hass_storage["guestbook.entries"]["data"]["entries"]
    assert stored["reason"]["code"] == "ring_then_door"
    assert stored["end_reason"]["code"] == "max_duration"
