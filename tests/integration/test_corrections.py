import json
from datetime import timedelta
from pathlib import Path

import probatio
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.guestbook.const import DOMAIN, EVENT_VISIT_CORRECTED, EVENT_VISIT_ENDED
from custom_components.guestbook.core import EffectiveKind

from .conftest import (
    ALEX_PHONE,
    DOOR,
    add_guest,
    advance,
    get_rings,
    get_visits,
    make_unanswered_ring,
    make_visit,
    ring,
)

CURRENT_VISIT = "sensor.guestbook_current_visit"
VISIT_ACTIVE = "binary_sensor.guestbook_visit_active"
COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"


def parse(value: str):
    return dt_util.parse_datetime(value)


async def correct(hass: HomeAssistant, entry_id: str, kind: str, **data):
    return await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": kind, **data}, blocking=True
    )


def stored_entries(hass_storage) -> list[dict]:
    return hass_storage["guestbook.entries"]["data"]["entries"]


async def open_visit(hass: HomeAssistant) -> str:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    return hass.states.get(CURRENT_VISIT).attributes["entry_id"]


async def test_visit_corrected_to_resident_leaves_every_calendar_but_stays_stored(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "resident")

    assert await get_visits(hass) == []
    assert await get_rings(hass) == []
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    assert stored["id"] == entry_id
    assert stored["kind"] == "visit"
    assert stored["reason"]["code"] == "ring_then_door"
    assert stored["correction"]["kind"] == "resident"
    assert stored["correction"]["source"] == "action"


async def test_open_visit_corrected_to_resident_is_closed_and_takes_no_more_signals(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    ended = async_capture_events(hass, EVENT_VISIT_ENDED)
    entry_id = await open_visit(hass)
    await advance(hass, freezer, timedelta(minutes=3))

    await correct(hass, entry_id, "resident")

    assert hass.states.get(VISIT_ACTIVE).state == "off"
    assert hass.states.get(CURRENT_VISIT).state == "unknown"
    assert hass.states.get("calendar.guestbook_visits").state == "off"
    (event,) = ended
    assert (event.data["entry_id"], event.data["reason"], event.data["duration"]) == (entry_id, "corrected", 180)
    hass.states.async_set(DOOR, "off")
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(hours=5))
    assert hass.states.get(VISIT_ACTIVE).state == "off"
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    assert [s["kind"] for s in stored["signals"]] == ["ring", "door_open"]
    assert stored["end"] == "2026-10-21T14:03:00+00:00"


async def test_visit_corrected_to_delivery_moves_to_the_rings_calendar(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "delivery")

    assert await get_visits(hass) == []
    (event,) = await get_rings(hass)
    assert event["summary"] == "Delivery"
    assert parse(event["start"]) == parse("2026-10-21T14:00:00+00:00")


async def test_open_visit_corrected_to_delivery_is_closed(hass: HomeAssistant, setup_guestbook):
    entry_id = await open_visit(hass)

    await correct(hass, entry_id, "delivery")

    assert hass.states.get(VISIT_ACTIVE).state == "off"
    assert [e["summary"] for e in await get_rings(hass)] == ["Delivery"]


async def test_unanswered_ring_corrected_to_visit_moves_to_the_visits_calendar(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_unanswered_ring(hass, freezer)

    await correct(hass, entry_id, "visit", guest_name="Alex")

    assert await get_rings(hass) == []
    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"


async def test_unanswered_ring_corrected_to_visit_without_a_name_is_a_plain_visit(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_unanswered_ring(hass, freezer)

    await correct(hass, entry_id, "visit")

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit"]


async def test_unknown_correction_keeps_the_entry_where_the_decision_put_it(
    hass: HomeAssistant, setup_guestbook, freezer
):
    visit_id = await make_visit(hass, freezer)
    await advance(hass, freezer, timedelta(minutes=10))
    ring_id = await make_unanswered_ring(hass, freezer)

    await correct(hass, visit_id, "unknown", note="no idea")
    await correct(hass, ring_id, "unknown")

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit (uncertain)"]
    assert [e["summary"] for e in await get_rings(hass)] == ["Unanswered ring"]


async def test_corrected_start_and_end_replace_the_shown_times(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "visit", start="2026-10-21T13:50:00+00:00", end="2026-10-21T15:10:00+00:00")

    (event,) = await get_visits(hass)
    assert parse(event["start"]) == parse("2026-10-21T13:50:00+00:00")
    assert parse(event["end"]) == parse("2026-10-21T15:10:00+00:00")


async def test_corrected_start_moves_the_event_out_of_a_queried_range(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "visit", start="2026-10-19T13:50:00+00:00", end="2026-10-19T15:10:00+00:00")

    assert await get_visits(hass) == []


async def test_description_keeps_the_decision_and_shows_the_correction(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "visit", guest_name="Alex", note="Neighbour")

    (event,) = await get_visits(hass)
    lines = event["description"].splitlines()
    assert "Started: ring followed by a door opening or presence" in lines
    assert any(
        line.startswith("Correction (action, ") and line.endswith("guest Alex, note: Neighbour") for line in lines
    )


async def test_corrected_event_fires_with_the_effective_entry(hass: HomeAssistant, setup_guestbook, freezer):
    corrected = async_capture_events(hass, EVENT_VISIT_CORRECTED)
    entry_id = await make_visit(hass, freezer)

    await correct(hass, entry_id, "visit", guest_name="Alex", end="2026-10-21T17:00:00+00:00")
    await correct(hass, entry_id, "resident")

    assert [e.data for e in corrected] == [
        {
            "entry_id": entry_id,
            "kind": "visit",
            "guest_name": "Alex",
            "guests": ["Alex"],
            "certainty": "uncertain",
            "start": "2026-10-21T14:00:00+00:00",
            "end": "2026-10-21T17:00:00+00:00",
        },
        {
            "entry_id": entry_id,
            "kind": "resident",
            "guest_name": None,
            "guests": [],
            "certainty": "uncertain",
            "start": "2026-10-21T14:00:00+00:00",
            "end": "2026-10-21T18:00:00+00:00",
        },
    ]


async def test_correct_entry_can_return_the_result(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    response = await hass.services.async_call(
        DOMAIN,
        "correct_entry",
        {"entry_id": entry_id, "kind": "visit", "guest_name": "Alex"},
        blocking=True,
        return_response=True,
    )

    assert response == {
        "entry_id": entry_id,
        "kind": "visit",
        "decision": "visit",
        "guests": ["Alex"],
        "start": "2026-10-21T14:00:00+00:00",
        "end": "2026-10-21T18:00:00+00:00",
    }
    assert await correct(hass, entry_id, "unknown") is None


async def test_open_visit_corrected_to_visit_names_the_guest_in_the_sensor(hass: HomeAssistant, setup_guestbook):
    entry_id = await open_visit(hass)

    await correct(hass, entry_id, "visit", guest_name="Alex")

    assert hass.states.get(CURRENT_VISIT).state == "Alex"
    assert hass.states.get(VISIT_ACTIVE).state == "on"


async def test_end_before_start_is_rejected(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)

    with pytest.raises(ServiceValidationError) as error:
        await correct(hass, entry_id, "visit", start="2026-10-21T19:00:00+00:00")

    assert error.value.translation_key == "end_before_start"


async def test_add_visit_matches_profiles_by_name_and_keeps_free_names(
    hass: HomeAssistant, setup_guestbook, hass_storage
):
    guest_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await hass.services.async_call(
        DOMAIN,
        "add_visit",
        {
            "guests": ["alex", "Pat"],
            "start": "2026-10-21T10:00:00+00:00",
            "end": "2026-10-21T11:30:00+00:00",
            "note": "Coffee",
        },
        blocking=True,
    )

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex, Pat"
    assert parse(event["start"]) == parse("2026-10-21T10:00:00+00:00")
    assert parse(event["end"]) == parse("2026-10-21T11:30:00+00:00")
    assert event["description"].splitlines() == ["Started: added by hand", "Notes:", "- Coffee"]
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = stored_entries(hass_storage)
    assert stored["kind"] == "visit"
    assert stored["reason"]["code"] == "manual"
    assert stored["guests"] == [{"id": guest_id, "name": "Alex"}, {"id": "", "name": "Pat"}]
    assert stored["notes"] == ["Coffee"]


async def test_add_visit_without_guests_or_note_is_a_plain_visit(hass: HomeAssistant, setup_guestbook):
    await hass.services.async_call(
        DOMAIN,
        "add_visit",
        {"start": "2026-10-21T10:00:00+00:00", "end": "2026-10-21T11:00:00+00:00"},
        blocking=True,
    )

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit"]


async def test_add_visit_with_the_end_before_the_start_is_rejected(hass: HomeAssistant, setup_guestbook):
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(
            DOMAIN,
            "add_visit",
            {"start": "2026-10-21T11:00:00+00:00", "end": "2026-10-21T10:00:00+00:00"},
            blocking=True,
        )

    assert error.value.translation_key == "end_before_start"
    assert await get_visits(hass) == []


async def test_add_note_shows_in_the_description_of_any_entry(hass: HomeAssistant, setup_guestbook, freezer):
    ring_id = await make_unanswered_ring(hass, freezer)

    await hass.services.async_call(
        DOMAIN, "add_note", {"entry_id": ring_id, "note": "Probably the postman"}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "add_note", {"entry_id": ring_id, "note": "Second note"}, blocking=True)

    (event,) = await get_rings(hass)
    assert event["description"].splitlines()[-3:] == ["Notes:", "- Probably the postman", "- Second note"]


@pytest.mark.parametrize(
    ("service", "data"),
    [
        ("correct_entry", {"kind": "resident"}),
        ("add_note", {"note": "hello"}),
    ],
)
async def test_unknown_entry_id_gives_a_translated_error(hass: HomeAssistant, setup_guestbook, service, data):
    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, service, {"entry_id": "nope", **data}, blocking=True)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "unknown_entry"
    assert error.value.translation_placeholders == {"entry_id": "nope"}


async def test_pending_ring_cannot_be_corrected_yet(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    (pending,) = setup_guestbook.runtime_data.async_entries(EffectiveKind.PENDING_RING)

    with pytest.raises(ServiceValidationError) as error:
        await correct(hass, pending.id, "resident")

    assert error.value.translation_key == "entry_pending"


async def test_unknown_kind_is_rejected_by_the_schema(hass: HomeAssistant, setup_guestbook):
    with pytest.raises(probatio.Invalid):
        await correct(hass, "x", "banana")


async def test_actions_need_a_loaded_entry(hass: HomeAssistant, setup_guestbook):
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    with pytest.raises(ServiceValidationError) as error:
        await correct(hass, "x", "resident")

    assert error.value.translation_key == "not_loaded"


async def test_actions_use_the_first_loaded_entry_when_there_are_more(
    hass: HomeAssistant, setup_guestbook, config_entry, freezer
):
    entry_id = await make_visit(hass, freezer)
    second = MockConfigEntry(domain=DOMAIN, title="Guestbook 2", data=dict(config_entry.data))
    second.add_to_hass(hass)
    assert await hass.config_entries.async_setup(second.entry_id)
    await hass.async_block_till_done()

    await correct(hass, entry_id, "delivery")
    await hass.services.async_call(
        DOMAIN,
        "add_visit",
        {"guests": ["Sam"], "start": "2026-10-20T10:00:00+00:00", "end": "2026-10-20T11:00:00+00:00"},
        blocking=True,
    )

    assert setup_guestbook.runtime_data.async_get_entry(entry_id).correction.kind == "delivery"
    assert len(setup_guestbook.runtime_data.async_entries(EffectiveKind.VISIT)) == 1
    assert second.runtime_data.async_get_entry(entry_id).correction is None


@pytest.mark.parametrize("language", ["en", "de"])
def test_new_errors_and_actions_are_translated(language):
    translations = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())

    assert {"unknown_entry", "entry_pending", "end_before_start", "not_loaded"} <= translations["exceptions"].keys()
    for action, fields in {
        "correct_entry": {"entry_id", "kind", "guest_name", "start", "end", "note"},
        "add_visit": {"guests", "start", "end", "note"},
        "add_note": {"entry_id", "note"},
    }.items():
        service = translations["services"][action]
        assert service["name"]
        assert service["description"]
        assert fields == service["fields"].keys()
