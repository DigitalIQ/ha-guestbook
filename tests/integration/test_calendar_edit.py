"""Editing and deleting entries from the calendar dialog of Home Assistant."""

import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.components.calendar import WEBSOCKET_EVENT_SCHEMA, CalendarEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import issue_registry as ir
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_capture_events

from custom_components.guestbook.const import DOMAIN, EVENT_VISIT_CORRECTED
from custom_components.guestbook.core import CorrectionKind, EffectiveKind

from .conftest import DOOR, add_guest, advance, get_rings, get_visits, make_unanswered_ring, make_visit, ring

VISITS = "calendar.guestbook_visits"
RINGS = "calendar.guestbook_rings"


def parse(value: str):
    return dt_util.parse_datetime(value)


def stored(setup_guestbook, entry_id: str):
    return setup_guestbook.runtime_data.async_get_entry(entry_id)


def dialog(event: dict, **changes) -> dict:
    """What the edit dialog sends back: the event as shown, with the user's changes."""
    sent = {"summary": event["summary"], "dtstart": event["start"], "dtend": event["end"]}
    if "description" in event:
        sent["description"] = event["description"]
    return sent | changes


async def update(hass: HomeAssistant, entity_id: str, uid: str, event: dict) -> None:
    """Save an edit like `calendar/event/update`: validated by the schema of Home Assistant, then the entity."""
    await hass.data["calendar"].get_entity(entity_id).async_update_event(uid, WEBSOCKET_EVENT_SCHEMA(event))


async def delete(hass: HomeAssistant, entity_id: str, uid: str) -> None:
    await hass.data["calendar"].get_entity(entity_id).async_delete_event(uid)


async def start_uncertain_visit(hass: HomeAssistant) -> str:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    return hass.states.get("sensor.guestbook_current_visit").attributes["entry_id"]


async def calendar_entity(hass: HomeAssistant, entity_id: str):
    return hass.data["calendar"].get_entity(entity_id)


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


@pytest.mark.parametrize("entity_id", [VISITS, RINGS])
async def test_both_calendars_offer_edit_and_delete(hass: HomeAssistant, setup_guestbook, entity_id):
    features = hass.states.get(entity_id).attributes["supported_features"]

    assert features == CalendarEntityFeature.UPDATE_EVENT | CalendarEntityFeature.DELETE_EVENT


async def test_events_carry_the_entry_id_as_uid_on_both_calendars(hass: HomeAssistant, setup_guestbook, freezer):
    visit_id = await make_visit(hass, freezer)
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    visits = await (await calendar_entity(hass, VISITS)).async_get_events(
        hass, dt_util.utcnow() - timedelta(days=1), dt_util.utcnow() + timedelta(days=1)
    )
    rings = await (await calendar_entity(hass, RINGS)).async_get_events(
        hass, dt_util.utcnow() - timedelta(days=1), dt_util.utcnow() + timedelta(days=1)
    )

    assert [e.uid for e in visits] == [visit_id]
    ring_entry = next(e for e in setup_guestbook.runtime_data.async_entries(EffectiveKind.UNANSWERED_RING))
    assert [e.uid for e in rings] == [ring_entry.id]


async def test_title_that_was_me_corrects_to_resident_and_keeps_the_decision(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="That was me"))

    assert await get_visits(hass) == []
    entry = stored(setup_guestbook, entry_id)
    assert entry.kind == "visit"
    assert entry.reason.code == "ring_then_door"
    assert (entry.correction.kind, entry.correction.source) == ("resident", "calendar")


async def test_german_title_and_odd_spelling_are_understood(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    calendar = await calendar_entity(hass, VISITS)
    (event,) = await get_visits(hass)

    await calendar.async_update_event(entry_id, dialog_event(event, summary="  war   ICH "))

    assert stored(setup_guestbook, entry_id).correction.kind == "resident"


def dialog_event(event: dict, **changes) -> dict:
    """Like `dialog`, with parsed datetimes as the calendar entity receives them from the websocket schema."""
    sent = dialog(event, **changes)
    return sent | {key: parse(sent[key]) for key in ("dtstart", "dtend") if isinstance(sent[key], str)}


async def test_title_delivery_moves_the_visit_to_the_rings_calendar(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Lieferung"))

    assert await get_visits(hass) == []
    assert [e["summary"] for e in await get_rings(hass)] == ["Delivery"]


async def test_title_dont_know_keeps_the_entry_and_records_the_answer(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Weiß nicht"))

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit (uncertain)"]
    assert stored(setup_guestbook, entry_id).correction.kind == "unknown"


async def test_title_with_a_name_makes_a_visit_of_that_guest_and_suggests_a_profile(
    hass: HomeAssistant, setup_guestbook, freezer
):
    corrected = async_capture_events(hass, EVENT_VISIT_CORRECTED)
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Besuch: Robin"))

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Robin"]
    assert stored(setup_guestbook, entry_id).correction.guest_name == "Robin"
    assert corrected[0].data["guest_name"] == "Robin"
    assert ir.async_get(hass).async_get_issue(DOMAIN, "guest_suggestion_robin") is not None


async def test_bare_name_of_a_known_guest_makes_no_suggestion(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", ["device_tracker.alex_phone"])
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="alex"))

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: alex"]
    assert ir.async_get(hass).async_get_issue(DOMAIN, "guest_suggestion_alex") is None


async def test_name_longer_than_the_limit_is_cut(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Visit: " + "A" * 100))

    assert stored(setup_guestbook, entry_id).correction.guest_name == "A" * 64


async def test_saving_the_dialog_unchanged_stores_nothing(hass: HomeAssistant, setup_guestbook, freezer):
    corrected = async_capture_events(hass, EVENT_VISIT_CORRECTED)
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event))

    entry = stored(setup_guestbook, entry_id)
    assert (entry.correction, entry.notes, corrected) == (None, [], [])


async def test_the_dialog_without_seconds_and_microseconds_is_unchanged(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    freezer.tick(timedelta(seconds=3.25))
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(hours=4))
    (entry_id,) = [e.id for e in setup_guestbook.runtime_data.async_entries(EffectiveKind.VISIT)]
    (event,) = await get_visits(hass)
    start = parse(event["start"]).replace(microsecond=0).isoformat()

    await update(hass, VISITS, entry_id, dialog(event, dtstart=start))

    assert stored(setup_guestbook, entry_id).correction is None


async def test_moved_times_become_display_overrides_and_the_stored_times_stay(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)
    start, end = parse(event["start"]), parse(event["end"])

    await update(
        hass,
        VISITS,
        entry_id,
        dialog(event, dtstart=(start + timedelta(minutes=5)).isoformat(), dtend=(end - timedelta(hours=1)).isoformat()),
    )

    (shown,) = await get_visits(hass)
    assert parse(shown["start"]) == start + timedelta(minutes=5)
    assert parse(shown["end"]) == end - timedelta(hours=1)
    entry = stored(setup_guestbook, entry_id)
    assert (entry.start, entry.end) == (start, end)
    assert entry.correction.kind == "unknown"
    assert entry.correction.source == "calendar"


async def test_naive_local_times_as_the_frontend_sends_them_are_understood(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)
    local_start = dt_util.as_local(parse(event["start"]) + timedelta(minutes=10)).replace(tzinfo=None, microsecond=0)

    local_end = dt_util.as_local(parse(event["end"])).replace(tzinfo=None, microsecond=0)

    await update(hass, VISITS, entry_id, dialog(event, dtstart=local_start.isoformat(), dtend=local_end.isoformat()))

    assert stored(setup_guestbook, entry_id).correction.start == parse(event["start"]) + timedelta(minutes=10)


async def test_end_before_start_against_the_stored_times_is_refused(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    calendar = await calendar_entity(hass, VISITS)
    (event,) = await get_visits(hass)
    late = parse(event["end"]) + timedelta(minutes=30)

    with pytest.raises(ServiceValidationError) as error:
        await calendar.async_update_event(entry_id, dialog_event(event, dtstart=late))
    assert error.value.translation_key == "end_before_start"
    assert stored(setup_guestbook, entry_id).correction is None


async def test_the_end_of_a_running_visit_is_ignored_but_its_start_can_move(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)
    (event,) = await get_visits(hass)
    start = parse(event["start"])

    await update(
        hass,
        VISITS,
        entry_id,
        dialog(
            event, dtstart=(start - timedelta(minutes=10)).isoformat(), dtend=(start + timedelta(hours=9)).isoformat()
        ),
    )

    entry = stored(setup_guestbook, entry_id)
    assert entry.correction.start == start - timedelta(minutes=10)
    assert entry.correction.end is None
    assert entry.open


async def test_added_description_text_becomes_a_note_and_the_log_stays_generated(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, description=event["description"] + "\nCame to fix the sink\n"))

    entry = stored(setup_guestbook, entry_id)
    assert entry.notes == ["Came to fix the sink"]
    assert entry.correction is None
    (shown,) = await get_visits(hass)
    assert shown["description"].endswith("Notes:\n- Came to fix the sink")
    assert shown["description"].startswith(event["description"].splitlines()[0])


async def test_saving_the_shown_description_again_does_not_repeat_notes(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)
    await update(hass, VISITS, entry_id, dialog(event, description=event["description"] + "\nCame to fix the sink"))
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event))

    assert stored(setup_guestbook, entry_id).notes == ["Came to fix the sink"]


async def test_a_removed_description_changes_nothing(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, description=""))

    entry = stored(setup_guestbook, entry_id)
    assert (entry.correction, entry.notes) == (None, [])


async def test_a_second_edit_keeps_the_times_and_the_note_of_the_first_correction(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    setup_guestbook.runtime_data.async_correct_entry(entry_id, CorrectionKind.UNKNOWN, note="Seen on camera")
    (event,) = await get_visits(hass)
    start = parse(event["start"])
    await update(hass, VISITS, entry_id, dialog(event, dtstart=(start + timedelta(minutes=5)).isoformat()))
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Visit: Alex"))

    correction = stored(setup_guestbook, entry_id).correction
    assert (correction.kind, correction.guest_name) == ("visit", "Alex")
    assert correction.start == start + timedelta(minutes=5)
    assert correction.note == "Seen on camera"


async def test_a_time_only_edit_of_a_corrected_visit_keeps_its_kind_and_name(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    setup_guestbook.runtime_data.async_correct_entry(entry_id, CorrectionKind.VISIT, guest_name="Alex")
    (event,) = await get_visits(hass)
    end = parse(event["end"])

    await update(hass, VISITS, entry_id, dialog(event, dtend=(end - timedelta(hours=1)).isoformat()))

    correction = stored(setup_guestbook, entry_id).correction
    assert (correction.kind, correction.guest_name, correction.end) == ("visit", "Alex", end - timedelta(hours=1))


async def test_an_unanswered_ring_edited_to_a_name_moves_to_the_visits_calendar(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_unanswered_ring(hass, freezer)
    (event,) = await get_rings(hass)

    await update(hass, RINGS, entry_id, dialog(event, summary="Sam"))

    assert await get_rings(hass) == []
    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Sam"]


async def test_a_delivery_edited_back_to_a_visit_returns_to_the_visits_calendar(
    hass: HomeAssistant, setup_guestbook, freezer
):
    entry_id = await make_visit(hass, freezer)
    setup_guestbook.runtime_data.async_correct_entry(entry_id, CorrectionKind.DELIVERY)
    (event,) = await get_rings(hass)

    await update(hass, RINGS, entry_id, dialog(event, summary="Visit"))

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit (uncertain)"]
    assert await get_rings(hass) == []


async def test_an_open_visit_edited_to_delivery_is_closed(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await start_uncertain_visit(hass)
    await advance(hass, freezer, timedelta(seconds=30))
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Delivery"))

    assert hass.states.get("binary_sensor.guestbook_visit_active").state == "off"
    assert not stored(setup_guestbook, entry_id).open


async def test_delete_hides_the_visit_but_keeps_it_stored_and_exported(
    hass: HomeAssistant, setup_guestbook, freezer, hass_config_dir
):
    entry_id = await make_visit(hass, freezer)

    await delete(hass, VISITS, entry_id)

    assert await get_visits(hass) == []
    assert await get_rings(hass) == []
    entry = stored(setup_guestbook, entry_id)
    assert (entry.kind, entry.correction.kind, entry.correction.source) == ("visit", "resident", "calendar")
    path, count = await setup_guestbook.runtime_data.async_export()
    assert count == 1
    (exported,) = (json.loads(line) for line in Path(path).read_text().splitlines())
    assert (exported["id"], exported["kind"], exported["correction"]["kind"]) == (entry_id, "visit", "resident")


async def test_delete_closes_a_running_visit(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await delete(hass, VISITS, entry_id)

    assert hass.states.get("binary_sensor.guestbook_visit_active").state == "off"
    assert not stored(setup_guestbook, entry_id).open


async def test_delete_hides_an_unanswered_ring_and_a_delivery(hass: HomeAssistant, setup_guestbook, freezer):
    ring_id = await make_unanswered_ring(hass, freezer)
    visit_id = await make_visit(hass, freezer)
    setup_guestbook.runtime_data.async_correct_entry(visit_id, CorrectionKind.DELIVERY)
    assert len(await get_rings(hass)) == 2

    await delete(hass, RINGS, ring_id)
    await delete(hass, RINGS, visit_id)

    assert await get_rings(hass) == []


@pytest.mark.parametrize("operation", ["update", "delete"])
async def test_an_unknown_uid_is_refused_with_a_message(hass: HomeAssistant, setup_guestbook, operation):
    event = {"summary": "x", "dtstart": "2026-10-21T10:00:00", "dtend": "2026-10-21T11:00:00"}

    with pytest.raises(ServiceValidationError) as error:
        await (update(hass, VISITS, "nope", event) if operation == "update" else delete(hass, VISITS, "nope"))

    assert error.value.translation_key == "unknown_entry"
    assert "no entry with the id nope" in str(error.value)


async def test_an_entry_of_the_other_calendar_is_refused(hass: HomeAssistant, setup_guestbook, freezer):
    ring_id = await make_unanswered_ring(hass, freezer)
    calendar = await calendar_entity(hass, VISITS)

    with pytest.raises(ServiceValidationError) as error:
        await calendar.async_delete_event(ring_id)

    assert error.value.translation_key == "not_in_calendar"
    assert stored(setup_guestbook, ring_id).correction is None


async def test_a_pending_ring_is_refused(hass: HomeAssistant, setup_guestbook):
    await ring(hass)
    (pending,) = setup_guestbook.runtime_data.async_entries(EffectiveKind.PENDING_RING)
    calendar = await calendar_entity(hass, RINGS)

    with pytest.raises(ServiceValidationError) as error:
        await calendar.async_delete_event(pending.id)

    assert error.value.translation_key == "entry_pending"


async def test_all_day_repeating_and_empty_edits_are_refused(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    calendar = await calendar_entity(hass, VISITS)
    (event,) = await get_visits(hass)
    day = dt_util.as_local(parse(event["start"])).date()

    cases = {
        "all_day": dialog_event(event, dtstart=day, dtend=day + timedelta(days=1)),
        "repeat": dialog_event(event, rrule="FREQ=DAILY"),
        "empty_title": dialog_event(event, summary="   "),
    }
    for key, sent in cases.items():
        with pytest.raises(ServiceValidationError) as error:
            await calendar.async_update_event(entry_id, sent)
        assert error.value.translation_key == f"calendar_{key}", key
    with pytest.raises(ServiceValidationError) as error:
        await calendar.async_update_event(entry_id, dialog_event(event), recurrence_id="x")
    assert error.value.translation_key == "calendar_repeat"
    assert stored(setup_guestbook, entry_id).correction is None


async def test_a_failed_edit_stores_no_note(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    calendar = await calendar_entity(hass, VISITS)
    (event,) = await get_visits(hass)
    late = parse(event["end"]) + timedelta(minutes=30)

    with pytest.raises(ServiceValidationError):
        await calendar.async_update_event(
            entry_id,
            dialog_event(event, dtstart=late, description=event["description"] + "\nNote"),
        )

    assert stored(setup_guestbook, entry_id).notes == []


async def test_the_correction_source_calendar_is_named_in_the_log(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    (event,) = await get_visits(hass)

    await update(hass, VISITS, entry_id, dialog(event, summary="Delivery"))

    (shown,) = await get_rings(hass)
    assert "Correction (calendar, " in shown["description"]
