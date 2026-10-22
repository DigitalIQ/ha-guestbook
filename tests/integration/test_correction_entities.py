import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import async_capture_events, mock_restore_cache

from custom_components.guestbook.const import DOMAIN, EVENT_VISIT_CORRECTED

from .conftest import (
    DOOR,
    advance,
    get_rings,
    get_visits,
    make_unanswered_ring,
    make_visit,
    ring,
)

LATEST_ENTRY = "sensor.guestbook_latest_entry"
GUEST_NAME = "text.guestbook_guest_name"
BUTTON_RESIDENT = "button.guestbook_that_was_me"
BUTTON_DELIVERY = "button.guestbook_delivery"
BUTTON_UNKNOWN = "button.guestbook_don_t_know"
BUTTON_VISIT = "button.guestbook_visit"
COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"


async def press(hass: HomeAssistant, entity_id: str) -> None:
    await hass.services.async_call("button", "press", {"entity_id": entity_id}, blocking=True)


async def set_guest_name(hass: HomeAssistant, value: str) -> None:
    await hass.services.async_call("text", "set_value", {"entity_id": GUEST_NAME, "value": value}, blocking=True)


# --- sensor: latest entry ---------------------------------------------------------------------------------------


async def test_latest_entry_is_unknown_without_an_entry(hass: HomeAssistant, setup_guestbook):
    state = hass.states.get(LATEST_ENTRY)

    assert state.state == "unknown"
    assert set(state.attributes) == {"friendly_name"}


async def test_latest_entry_shows_the_title_of_the_calendar_and_the_entry_data(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)

    state = hass.states.get(LATEST_ENTRY)

    assert state.state == "Visit (uncertain)"
    assert state.state == (await get_visits(hass))[0]["summary"]
    assert set(state.attributes) - {"friendly_name"} == {"entry_id", "start", "end", "kind", "corrected"}
    assert state.attributes["entry_id"] == entry_id
    assert state.attributes["start"] == "2026-10-21T14:00:00+00:00"
    assert state.attributes["end"] == "2026-10-21T18:00:00+00:00"
    assert state.attributes["kind"] == "visit"
    assert state.attributes["corrected"] is False


async def test_latest_entry_of_an_open_visit_has_no_end(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    state = hass.states.get(LATEST_ENTRY)

    assert state.state == "Visit (uncertain)"
    assert state.attributes["end"] is None


async def test_latest_entry_follows_corrections_with_the_effective_kind(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)

    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "delivery"}, blocking=True)

    state = hass.states.get(LATEST_ENTRY)
    assert state.state == "Delivery"
    assert state.attributes["kind"] == "delivery"
    assert state.attributes["corrected"] is True


async def test_latest_entry_keeps_a_visit_corrected_to_resident(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)

    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "resident"}, blocking=True)

    state = hass.states.get(LATEST_ENTRY)
    assert state.attributes["kind"] == "resident_arrival"
    assert state.attributes["corrected"] is True


async def test_latest_entry_moves_on_to_a_newer_entry_but_not_to_a_pending_ring(
    hass: HomeAssistant, setup_guestbook, freezer
):
    first = await make_visit(hass, freezer)
    assert hass.states.get(LATEST_ENTRY).attributes["entry_id"] == first

    await ring(hass)
    assert hass.states.get(LATEST_ENTRY).attributes["entry_id"] == first

    await advance(hass, freezer, timedelta(minutes=6))
    state = hass.states.get(LATEST_ENTRY)
    assert state.attributes["entry_id"] != first
    assert state.state == "Unanswered ring"
    assert state.attributes["kind"] == "unanswered_ring"


async def test_latest_entry_follows_the_language_of_home_assistant(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    hass.config.language = "de"

    await hass.services.async_call(DOMAIN, "add_note", {"note": "x"}, blocking=True)  # any change refreshes it

    assert hass.states.get(LATEST_ENTRY).state == "Besuch (unsicher)"


async def test_latest_entry_state_is_cut_below_the_limit_of_home_assistant(hass: HomeAssistant, setup_guestbook):
    guests = [f"{letter}" * 64 for letter in "ABCDEF"]

    await hass.services.async_call(
        DOMAIN,
        "add_visit",
        {"guests": guests, "start": "2026-10-21T10:00:00+00:00", "end": "2026-10-21T11:00:00+00:00"},
        blocking=True,
    )

    state = hass.states.get(LATEST_ENTRY)
    assert 200 < len(state.state) < 255
    assert state.state.startswith("Visit: AAAA")
    assert state.state.endswith("…")


# --- text: guest name -------------------------------------------------------------------------------------------


async def test_guest_name_is_empty_by_default_and_a_plain_text_of_64_characters(hass: HomeAssistant, setup_guestbook):
    state = hass.states.get(GUEST_NAME)

    assert state.state == ""
    assert state.attributes["mode"] == "text"
    assert state.attributes["max"] == 64


async def test_guest_name_can_be_set(hass: HomeAssistant, setup_guestbook):
    await set_guest_name(hass, "Alex")

    assert hass.states.get(GUEST_NAME).state == "Alex"


async def test_guest_name_longer_than_64_characters_is_refused(hass: HomeAssistant, setup_guestbook):
    with pytest.raises(ValueError, match="too long"):
        await set_guest_name(hass, "A" * 65)

    assert hass.states.get(GUEST_NAME).state == ""


async def test_guest_name_survives_a_restart(hass: HomeAssistant, setup_guestbook):
    await set_guest_name(hass, "Alex")

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(GUEST_NAME).state == "Alex"


@pytest.mark.parametrize("stored", ["unknown", "unavailable"])
async def test_guest_name_ignores_a_state_that_is_no_text(hass: HomeAssistant, setup_guestbook, stored):
    mock_restore_cache(hass, [State(GUEST_NAME, stored)])

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert hass.states.get(GUEST_NAME).state == ""


# --- buttons ----------------------------------------------------------------------------------------------------


async def test_the_entities_belong_to_the_guestbook_device(hass: HomeAssistant, setup_guestbook):
    entities = er.async_get(hass)
    device = dr.async_get(hass).async_get_device_by_identifier(
        (DOMAIN, setup_guestbook.entry_id), setup_guestbook.entry_id
    )
    expected = {LATEST_ENTRY, GUEST_NAME, BUTTON_RESIDENT, BUTTON_DELIVERY, BUTTON_UNKNOWN, BUTTON_VISIT}

    assert {e.entity_id for e in er.async_entries_for_device(entities, device.id)} >= expected


async def test_the_buttons_are_named_in_english(hass: HomeAssistant, setup_guestbook):
    names = {
        entity_id: hass.states.get(entity_id).attributes["friendly_name"]
        for entity_id in (BUTTON_RESIDENT, BUTTON_DELIVERY, BUTTON_UNKNOWN, BUTTON_VISIT, GUEST_NAME, LATEST_ENTRY)
    }

    assert names == {
        BUTTON_RESIDENT: "Guestbook That was me",
        BUTTON_DELIVERY: "Guestbook Delivery",
        BUTTON_UNKNOWN: "Guestbook Don't know",
        BUTTON_VISIT: "Guestbook Visit",
        GUEST_NAME: "Guestbook Guest name",
        LATEST_ENTRY: "Guestbook Latest entry",
    }


async def test_the_entities_are_named_in_german(hass: HomeAssistant, setup_guestbook):
    hass.config.language = "de"
    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    names = {
        entity_id: hass.states.get(entity_id).attributes["friendly_name"]
        for entity_id in (BUTTON_RESIDENT, BUTTON_DELIVERY, BUTTON_UNKNOWN, BUTTON_VISIT, GUEST_NAME, LATEST_ENTRY)
    }

    assert names == {
        BUTTON_RESIDENT: "Guestbook War ich",
        BUTTON_DELIVERY: "Guestbook Lieferung",
        BUTTON_UNKNOWN: "Guestbook Weiß nicht",
        BUTTON_VISIT: "Guestbook Besuch",
        GUEST_NAME: "Guestbook Gastname",
        LATEST_ENTRY: "Guestbook Letzter Eintrag",
    }


@pytest.mark.parametrize(
    ("button", "kind"),
    [(BUTTON_RESIDENT, "resident"), (BUTTON_DELIVERY, "delivery"), (BUTTON_UNKNOWN, "unknown")],
)
async def test_a_button_corrects_the_latest_entry_with_the_source_button(
    hass: HomeAssistant, setup_guestbook, freezer, button, kind
):
    older = await make_visit(hass, freezer)
    latest = await make_unanswered_ring(hass, freezer)

    await press(hass, button)

    runtime = setup_guestbook.runtime_data
    assert runtime.async_get_entry(older).correction is None
    correction = runtime.async_get_entry(latest).correction
    assert (correction.kind, correction.source, correction.guest_name) == (kind, "button", None)
    assert hass.states.get(LATEST_ENTRY).attributes["corrected"] is True


async def test_the_resident_and_delivery_buttons_move_the_entry(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)

    await press(hass, BUTTON_DELIVERY)
    assert await get_visits(hass) == []
    assert [e["summary"] for e in await get_rings(hass)] == ["Delivery"]

    await press(hass, BUTTON_RESIDENT)
    assert await get_rings(hass) == []
    assert hass.states.get(LATEST_ENTRY).state == "Resident arrival"


async def test_the_visit_button_uses_the_guest_name_and_clears_the_field(hass: HomeAssistant, setup_guestbook, freezer):
    await make_unanswered_ring(hass, freezer)
    await set_guest_name(hass, "  Alex ")

    await press(hass, BUTTON_VISIT)

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    correction = setup_guestbook.runtime_data.async_get_entry(
        hass.states.get(LATEST_ENTRY).attributes["entry_id"]
    ).correction
    assert (correction.kind, correction.source, correction.guest_name) == ("visit", "button", "Alex")
    assert hass.states.get(GUEST_NAME).state == ""


async def test_the_visit_button_without_a_name_makes_a_visit_without_a_name(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await make_unanswered_ring(hass, freezer)

    await press(hass, BUTTON_VISIT)

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit"
    assert setup_guestbook.runtime_data.async_latest_entry().correction.guest_name is None


async def test_the_other_buttons_leave_the_guest_name_alone(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    await set_guest_name(hass, "Alex")

    await press(hass, BUTTON_UNKNOWN)

    assert hass.states.get(GUEST_NAME).state == "Alex"


async def test_a_button_fires_the_corrected_event(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    events = async_capture_events(hass, EVENT_VISIT_CORRECTED)

    await press(hass, BUTTON_DELIVERY)

    assert [(e.data["entry_id"], e.data["kind"]) for e in events] == [(entry_id, "delivery")]


@pytest.mark.parametrize("button", [BUTTON_RESIDENT, BUTTON_DELIVERY, BUTTON_UNKNOWN, BUTTON_VISIT])
async def test_a_button_without_an_entry_gives_a_translated_error_and_keeps_the_name(
    hass: HomeAssistant, setup_guestbook, button
):
    await set_guest_name(hass, "Alex")

    with pytest.raises(HomeAssistantError) as error:
        await press(hass, button)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "no_latest_entry"
    assert hass.states.get(GUEST_NAME).state == "Alex"


async def test_a_button_ignores_a_pending_ring(hass: HomeAssistant, setup_guestbook):
    await ring(hass)

    with pytest.raises(HomeAssistantError) as error:
        await press(hass, BUTTON_DELIVERY)

    assert error.value.translation_key == "no_latest_entry"


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_entities_are_translated(language):
    entity = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())["entity"]

    assert entity["sensor"]["latest_entry"]["name"]
    assert entity["text"]["guest_name"]["name"]
    assert {"resident", "delivery", "unknown", "visit"} == entity["button"].keys()
