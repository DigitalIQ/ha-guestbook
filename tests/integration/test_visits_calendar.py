from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from custom_components.guestbook.const import CONF_DOORBELLS

from .conftest import DOOR, DOORBELL, PRESENCE, advance, get_rings, get_visits, ring


async def test_ring_then_door_opening_shows_an_uncertain_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=30))

    (visit,) = await get_visits(hass)

    assert visit["summary"] == "Visit (uncertain)"
    assert dt_util.parse_datetime(visit["start"]) == dt_util.parse_datetime("2026-10-21T14:00:00+00:00")
    assert dt_util.parse_datetime(visit["end"]) == dt_util.utcnow()


async def test_calendar_entity_names_the_open_visit(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()

    assert hass.states.get("calendar.guestbook_visits").attributes["message"] == "Visit (uncertain)"


async def test_door_opening_without_a_ring_shows_nothing(hass: HomeAssistant, setup_guestbook):
    hass.states.async_set(DOOR, "on")
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_ring_alone_shows_nothing(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    assert await get_visits(hass) == []


async def test_door_opening_after_the_ring_window_shows_nothing(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_door_closing_and_presence_off_do_not_start_visits(hass: HomeAssistant, setup_guestbook):
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await ring(hass)
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(PRESENCE, "off")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_unavailable_sources_are_ignored(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    hass.states.async_set(DOOR, "unavailable")
    hass.states.async_set(DOOR, "on")
    hass.states.async_set(PRESENCE, "unknown")
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_doorbell_event_without_a_timestamp_is_not_a_ring(hass: HomeAssistant, setup_guestbook):
    hass.states.async_set(DOORBELL, "unavailable")
    hass.states.async_set(DOORBELL, "not a timestamp")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_binary_sensor_doorbell_rings_on_the_rising_edge(hass: HomeAssistant, config_entry, freezer):
    freezer.move_to("2026-10-21 14:00:00+00:00")
    config_entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(
        config_entry, data={**config_entry.data, CONF_DOORBELLS: ["binary_sensor.bell"]}
    )
    hass.states.async_set("binary_sensor.bell", "off")
    hass.states.async_set(DOOR, "off")
    await hass.config_entries.async_setup(config_entry.entry_id)
    await hass.async_block_till_done()

    hass.states.async_set("binary_sensor.bell", "on")
    hass.states.async_set("binary_sensor.bell", "off")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert len(await get_visits(hass)) == 1


async def test_visit_survives_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    (before,) = await get_visits(hass)

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    (after,) = await get_visits(hass)
    assert after["start"] == before["start"]
    assert after["summary"] == before["summary"]


async def test_pending_ring_survives_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert len(await get_visits(hass)) == 1


async def test_expired_pending_ring_is_stored_as_unanswered_ring(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    (stored,) = hass_storage["guestbook.entries"]["data"]["entries"]
    assert stored["kind"] == "unanswered_ring"
    assert stored["reason"]["code"] == "ring_no_entry"
    assert stored["end"] == "2026-10-21T14:01:00+00:00"


async def test_doorbell_event_after_reconnect_is_not_a_ring(hass: HomeAssistant, setup_guestbook):
    hass.states.async_set(DOORBELL, "unavailable")
    hass.states.async_set(DOORBELL, "2026-10-20T08:00:00.000+00:00")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_pending_ring_that_expires_during_downtime_is_not_a_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    freezer.tick(timedelta(minutes=10))

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await get_visits(hass) == []


async def test_rings_merged_into_a_visit_leave_one_stored_entry(hass: HomeAssistant, setup_guestbook, hass_storage):
    await ring(hass)
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = hass_storage["guestbook.entries"]["data"]["entries"]
    assert stored["kind"] == "visit"


async def test_description_holds_the_full_log_with_condensed_presence(hass: HomeAssistant, setup_guestbook, freezer):
    await hass.config.async_set_time_zone("Europe/Berlin")
    hass.states.async_set(DOOR, "off", {"friendly_name": "Front door"})
    hass.states.async_set(PRESENCE, "off", {"friendly_name": "Hall presence"})
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(DOOR, "on", {"friendly_name": "Front door"})
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=2))
    hass.states.async_set(PRESENCE, "on", {"friendly_name": "Hall presence"})
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(PRESENCE, "off", {"friendly_name": "Hall presence"})
    await hass.async_block_till_done()

    (visit,) = await get_visits(hass)

    assert visit["description"].splitlines() == [
        "16:00 front doorbell: ring",
        "16:01 Front door: opened",
        "Hall presence 16:03–16:33",
        "",
        "Started: ring followed by a door opening or presence",
    ]


async def test_title_and_description_follow_the_home_assistant_language(hass: HomeAssistant, setup_guestbook, freezer):
    hass.config.language = "de"
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    (visit,) = await get_visits(hass)

    assert visit["summary"] == "Besuch (unsicher)"
    assert visit["description"].splitlines()[-1] == "Beginn: Klingeln, danach Türöffnung oder Anwesenheit"
    assert hass.states.get("calendar.guestbook_visits").attributes["message"] == "Besuch (unsicher)"


async def test_unanswered_ring_title_is_translated(hass: HomeAssistant, setup_guestbook, freezer):
    hass.config.language = "de"
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    (event,) = await get_rings(hass)

    assert event["summary"] == "Klingeln ohne Einlass"
