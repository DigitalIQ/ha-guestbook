"""A guest who comes back the same day keeps every visit, across a restart and on the day of the DST change."""

from datetime import datetime

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .conftest import ALEX_PHONE, DOOR, PRESENCE, add_guest, advance, ring, set_tracker


async def step(hass: HomeAssistant, freezer, to: str) -> None:
    """Let the clock run to `to` (UTC, on 2026-10-25) and fire the timers on the way."""
    await advance(hass, freezer, datetime.fromisoformat(f"2026-10-25T{to}+00:00") - dt_util.utcnow())


async def visits_between(hass: HomeAssistant, start: str, end: str) -> list[str]:
    calendar = hass.data["calendar"].get_entity("calendar.guestbook_visits")
    events = await calendar.async_get_events(
        hass, dt_util.as_utc(datetime.fromisoformat(start)), dt_util.as_utc(datetime.fromisoformat(end))
    )
    return [event.start.isoformat() for event in events]


async def test_a_guest_returning_the_same_day_keeps_all_visits(hass: HomeAssistant, setup_guestbook, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    freezer.move_to("2026-10-25 11:00:00+00:00")

    # First visit: ring, presence, the phone joins and leaves.
    await step(hass, freezer, "11:30:00")
    await ring(hass)
    await step(hass, freezer, "11:30:20")
    hass.states.async_set(PRESENCE, "on")
    await step(hass, freezer, "11:31:00")
    await set_tracker(hass, ALEX_PHONE, "home")
    await step(hass, freezer, "11:40:00")
    await set_tracker(hass, ALEX_PHONE, "not_home")
    hass.states.async_set(PRESENCE, "off")

    # Second visit: ring, door, the phone joins, stays for two hours and leaves.
    await step(hass, freezer, "13:00:00")
    await ring(hass)
    await step(hass, freezer, "13:00:02")
    hass.states.async_set(DOOR, "on")
    await step(hass, freezer, "13:01:00")
    hass.states.async_set(DOOR, "off")
    await step(hass, freezer, "13:02:00")
    await set_tracker(hass, ALEX_PHONE, "home")
    await step(hass, freezer, "14:45:00")
    await set_tracker(hass, ALEX_PHONE, "not_home")

    # Third visit: the phone comes back, a ring during that visit joins it.
    await step(hass, freezer, "16:00:00")
    await set_tracker(hass, ALEX_PHONE, "home")
    await step(hass, freezer, "16:00:10")
    hass.states.async_set(DOOR, "on")
    await step(hass, freezer, "16:01:30")
    await ring(hass)
    await step(hass, freezer, "16:02:00")
    hass.states.async_set(PRESENCE, "on")
    await step(hass, freezer, "17:15:00")
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await step(hass, freezer, "17:30:00")

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    expected = [
        "2026-10-25T11:30:00+00:00",
        "2026-10-25T13:00:00+00:00",
        "2026-10-25T16:00:00+00:00",
    ]
    assert await visits_between(hass, "2026-10-25T00:00:00+02:00", "2026-10-26T00:00:00+01:00") == expected
    assert await visits_between(hass, "2026-10-25T12:00:00+01:00", "2026-10-25T17:30:00+01:00") == expected
