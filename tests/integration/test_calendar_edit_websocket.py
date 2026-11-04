"""The websocket commands of the calendar dialog (`calendar/event/update` and `calendar/event/delete`).

The client signs in before `setup_guestbook` moves the clock into the past, and no test moves the clock again:
the websocket connection does not survive `async_fire_time_changed`. Visits are therefore added by hand.
"""

from datetime import timedelta

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from .conftest import get_rings, get_visits

VISITS = "calendar.guestbook_visits"
RINGS = "calendar.guestbook_rings"


@pytest.fixture
async def ws(hass: HomeAssistant, hass_ws_client):
    assert await async_setup_component(hass, "calendar", {})  # its views must exist before the client starts the server
    return await hass_ws_client(hass)


@pytest.fixture
async def setup_guestbook(ws, setup_guestbook):
    return setup_guestbook


async def send(ws, command: str, entity_id: str, uid: str, **extra) -> dict:
    await ws.send_json_auto_id({"type": f"calendar/event/{command}", "entity_id": entity_id, "uid": uid, **extra})
    return await ws.receive_json()


def hand_added_visit(setup_guestbook) -> str:
    now = dt_util.utcnow()
    return setup_guestbook.runtime_data.async_add_visit(["Alex"], now - timedelta(hours=2), now - timedelta(hours=1)).id


def local(value) -> str:
    """The time as the dialog sends it: local time of the home, without offset."""
    return dt_util.as_local(value).replace(tzinfo=None).isoformat()


async def test_the_dialog_saves_a_new_title_and_description_through_the_websocket(
    hass: HomeAssistant, setup_guestbook, ws
):
    entry_id = hand_added_visit(setup_guestbook)
    (event,) = await get_visits(hass)
    start, end = dt_util.parse_datetime(event["start"]), dt_util.parse_datetime(event["end"])
    edit = {
        "summary": "Lieferung",
        "dtstart": local(start),
        "dtend": local(end),
        "description": event["description"] + "\nLeft it with the neighbour",
    }

    result = await send(ws, "update", VISITS, entry_id, event=edit)

    assert result["success"] is True
    assert await get_visits(hass) == []
    (delivery,) = await get_rings(hass)
    assert delivery["summary"] == "Delivery"
    assert delivery["description"].endswith("Notes:\n- Left it with the neighbour")
    assert setup_guestbook.runtime_data.async_get_entry(entry_id).correction.source == "calendar"


async def test_the_dialog_deletes_through_the_websocket(hass: HomeAssistant, setup_guestbook, ws):
    entry_id = hand_added_visit(setup_guestbook)

    result = await send(ws, "delete", VISITS, entry_id, recurrence_id="", recurrence_range="")

    assert result["success"] is True
    assert await get_visits(hass) == []
    assert setup_guestbook.runtime_data.async_get_entry(entry_id) is not None


async def test_a_refused_edit_reaches_the_dialog_as_a_translated_message(hass: HomeAssistant, setup_guestbook, ws):
    result = await send(
        ws,
        "update",
        VISITS,
        "nope",
        event={"summary": "x", "dtstart": "2026-10-21T10:00:00", "dtend": "2026-10-21T11:00:00"},
    )

    assert result["success"] is False
    assert result["error"]["code"] == "failed"
    assert "no entry with the id nope" in result["error"]["message"]


async def test_the_all_day_switch_of_the_dialog_is_refused_with_a_message(hass: HomeAssistant, setup_guestbook, ws):
    entry_id = hand_added_visit(setup_guestbook)

    result = await send(
        ws, "update", VISITS, entry_id, event={"summary": "Visit: Alex", "dtstart": "2026-10-21", "dtend": "2026-10-22"}
    )

    assert result["success"] is False
    assert 'Switch off "All day"' in result["error"]["message"]
