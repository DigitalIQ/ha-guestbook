from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.guestbook.const import EVENT_VISIT_ENDED, EVENT_VISIT_EVENT, EVENT_VISIT_STARTED

from .conftest import (
    ALEX_PHONE,
    DOOR,
    LOCK,
    PRESENCE,
    RESIDENT_BUTTON,
    SAM_PHONE,
    add_guest,
    advance,
    ring,
    set_tracker,
)

CURRENT_VISIT = "sensor.guestbook_current_visit"


@pytest.fixture
def started(hass: HomeAssistant):
    return async_capture_events(hass, EVENT_VISIT_STARTED)


@pytest.fixture
def signals(hass: HomeAssistant):
    return async_capture_events(hass, EVENT_VISIT_EVENT)


@pytest.fixture
def ended(hass: HomeAssistant):
    return async_capture_events(hass, EVENT_VISIT_ENDED)


async def test_started_fires_when_ring_and_door_make_a_visit(hass: HomeAssistant, setup_guestbook, freezer, started):
    await ring(hass)
    assert started == []
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    (event,) = started
    assert event.data == {
        "entry_id": hass.states.get(CURRENT_VISIT).attributes["entry_id"],
        "guests": [],
        "certainty": "uncertain",
        "start": "2026-10-21T14:00:00+00:00",
    }


async def test_started_names_the_guest_of_a_phone_visit(hass: HomeAssistant, setup_guestbook, started):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")

    (event,) = started
    assert event.data["guests"] == ["Alex"]
    assert event.data["certainty"] == "certain"
    assert event.data["start"] == "2026-10-21T14:00:00+00:00"


async def test_door_opening_that_makes_the_visit_is_not_a_visit_event(
    hass: HomeAssistant, setup_guestbook, started, signals
):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert len(started) == 1
    assert signals == []


async def test_visit_event_fires_for_every_signal_added_to_the_open_visit(
    hass: HomeAssistant, setup_guestbook, freezer, started, signals
):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=5))

    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()
    hass.states.async_set(LOCK, "unlocked")
    await hass.async_block_till_done()

    entry_id = started[0].data["entry_id"]
    assert [(e.data["signal"], e.data["source"]) for e in signals] == [
        ("presence_on", PRESENCE),
        ("lock", LOCK),
    ]
    assert signals[0].data == {
        "entry_id": entry_id,
        "guests": [],
        "certainty": "uncertain",
        "signal": "presence_on",
        "source": PRESENCE,
        "time": "2026-10-21T14:05:00+00:00",
    }


async def test_guest_phone_joining_an_uncertain_visit_is_a_visit_event(
    hass: HomeAssistant, setup_guestbook, started, signals
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    await set_tracker(hass, ALEX_PHONE, "home")

    assert len(started) == 1
    (event,) = signals
    assert event.data["signal"] == "guest_home"
    assert event.data["source"] == ALEX_PHONE
    assert event.data["guests"] == ["Alex"]
    assert event.data["certainty"] == "certain"


async def test_ended_fires_with_start_end_and_duration(hass: HomeAssistant, setup_guestbook, freezer, started, ended):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await add_guest(hass, setup_guestbook, "Sam", [SAM_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=10))
    await set_tracker(hass, SAM_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=50))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await set_tracker(hass, SAM_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=4))
    assert ended == []
    await advance(hass, freezer, timedelta(minutes=1))

    (event,) = ended
    assert event.data == {
        "entry_id": started[0].data["entry_id"],
        "guests": ["Alex", "Sam"],
        "certainty": "certain",
        "start": "2026-10-21T14:00:00+00:00",
        "end": "2026-10-21T15:00:00+00:00",
        "duration": 3600,
        "reason": "guests_left",
    }


async def test_ended_fires_for_an_uncertain_visit(hass: HomeAssistant, setup_guestbook, freezer, ended):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    await advance(hass, freezer, timedelta(hours=4))

    (event,) = ended
    assert event.data["certainty"] == "uncertain"
    assert event.data["duration"] == 4 * 3600
    assert event.data["reason"] == "max_duration"


async def test_ended_reason_is_door_then_quiet_for_a_door_ended_visit(
    hass: HomeAssistant, setup_guestbook, freezer, ended
):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    (event,) = ended
    assert event.data["reason"] == "door_then_quiet"


async def test_started_visit_that_becomes_a_resident_arrival_fires_ended(
    hass: HomeAssistant, setup_guestbook, freezer, started, ended
):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=1))
    hass.states.async_set(RESIDENT_BUTTON, "on")
    await hass.async_block_till_done()

    (event,) = ended
    assert event.data == {
        "entry_id": started[0].data["entry_id"],
        "guests": [],
        "certainty": "uncertain",
        "start": "2026-10-21T14:00:00+00:00",
        "end": "2026-10-21T14:01:00+00:00",
        "duration": 60,
        "reason": "resident_arrival",
    }
    assert hass.states.get("binary_sensor.guestbook_visit_active").state == "off"
    assert hass.states.get(CURRENT_VISIT).state == "unknown"


async def test_no_events_for_a_resident_arrival(hass: HomeAssistant, setup_guestbook, freezer, started, signals, ended):
    hass.states.async_set(RESIDENT_BUTTON, "on")
    await hass.async_block_till_done()
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(hours=5))

    assert started == signals == ended == []


async def test_no_events_for_an_unanswered_ring(hass: HomeAssistant, setup_guestbook, freezer, started, signals, ended):
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    assert started == signals == ended == []
