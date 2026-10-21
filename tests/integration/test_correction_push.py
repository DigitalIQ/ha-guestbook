from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.guestbook.const import CONF_RESIDENTS, EVENT_VISIT_CORRECTED
from custom_components.guestbook.core import EffectiveKind

from .conftest import (
    ALEX_PHONE,
    DOOR,
    add_guest,
    add_phone,
    advance,
    get_rings,
    get_visits,
    ring,
    set_options,
    set_tracker,
)

PIXEL_SERVICE = "mobile_app_pixel_of_alex"
IPHONE_SERVICE = "mobile_app_iphone_of_sam"
MESSENGER = "notify.family_messenger"
ACTION_EVENT = "mobile_app_notification_action"


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


async def start_uncertain_visit(hass: HomeAssistant) -> str:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    return hass.states.get("sensor.guestbook_current_visit").attributes["entry_id"]


async def answer(hass: HomeAssistant, action: str, **data) -> None:
    hass.bus.async_fire(ACTION_EVENT, {"action": action, **data})
    await hass.async_block_till_done()


def action(config_entry, kind: str, entry_id: str) -> str:
    """The id of the button `kind` of the question for `entry_id`, with the token the entry holds."""
    return f"GUESTBOOK_{kind}_{entry_id}_{_entry(config_entry, entry_id).question_token}"


async def select_phone(hass: HomeAssistant, entry, name="Pixel of Alex", os_name="Android", **options) -> list:
    device_id = await add_phone(hass, name, os_name)
    await set_options(hass, entry, phones=[device_id], **options)
    return async_mock_service(hass, "notify", f"mobile_app_{name.casefold().replace(' ', '_')}")


async def test_uncertain_visit_asks_the_phone_with_buttons_and_a_tag(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, os_name="iOS", push_arrival=False)

    entry_id = await start_uncertain_visit(hass)

    (call,) = calls
    assert call.data["title"] == "Who was that?"
    assert call.data["data"]["tag"] == entry_id
    actions = call.data["data"]["actions"]
    token = _entry(setup_guestbook, entry_id).question_token
    assert token
    assert [(a["action"], a["title"]) for a in actions] == [
        (f"GUESTBOOK_RESIDENT_{entry_id}_{token}", "That was me"),
        (f"GUESTBOOK_DELIVERY_{entry_id}_{token}", "Delivery"),
        (f"GUESTBOOK_VISIT_{entry_id}_{token}", "Visit"),
        (f"GUESTBOOK_UNKNOWN_{entry_id}_{token}", "Don't know"),
    ]
    assert actions[2]["behavior"] == "textInput"
    assert actions[2]["textInputPlaceholder"] == "Name of the guest"
    assert actions[2]["textInputButtonTitle"] == "Save"


async def test_android_phones_get_three_buttons(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, os_name="Android", push_arrival=False)

    await start_uncertain_visit(hass)

    assert [a["title"] for a in calls[0].data["data"]["actions"]] == ["That was me", "Delivery", "Visit"]


async def test_the_question_is_translated(hass: HomeAssistant, setup_guestbook):
    hass.config.language = "de"
    calls = await select_phone(hass, setup_guestbook, os_name="iOS", push_arrival=False)

    await start_uncertain_visit(hass)

    assert calls[0].data["title"] == "Wer war das?"
    assert [a["title"] for a in calls[0].data["data"]["actions"]] == ["War ich", "Lieferung", "Besuch", "Weiß nicht"]


async def test_the_question_is_sent_even_when_a_resident_is_home(hass: HomeAssistant, setup_guestbook):
    hass.states.async_set("person.sam", "home")
    hass.config_entries.async_update_entry(
        setup_guestbook, data={**setup_guestbook.data, CONF_RESIDENTS: ["person.sam"]}
    )
    calls = await select_phone(hass, setup_guestbook)

    await start_uncertain_visit(hass)

    assert [c.data["title"] for c in calls] == ["Who was that?"]


async def test_the_question_can_be_switched_off(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, push_correction=False)

    await start_uncertain_visit(hass)

    assert [c.data["title"] for c in calls] == ["Visit"]


async def test_certain_visits_and_unanswered_rings_get_no_question(hass: HomeAssistant, setup_guestbook, freezer):
    calls = await select_phone(hass, setup_guestbook, push_arrival=False)
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    assert calls == []


async def test_notify_entities_get_text_with_the_entry_id_and_the_action_hint(hass: HomeAssistant, setup_guestbook):
    messenger = async_mock_service(hass, "notify", "send_message")
    await set_options(hass, setup_guestbook, notify_entities=[MESSENGER], push_arrival=False)

    entry_id = await start_uncertain_visit(hass)

    (call,) = messenger
    assert call.data["entity_id"] == [MESSENGER]
    assert entry_id in call.data["message"]
    assert "guestbook.correct_entry" in call.data["message"]
    assert "data" not in call.data


async def test_answering_resident_saves_a_push_correction_and_closes_the_visit(hass: HomeAssistant, setup_guestbook):
    await select_phone(hass, setup_guestbook)
    entry_id = await start_uncertain_visit(hass)

    await answer(hass, action(setup_guestbook, "RESIDENT", entry_id))

    entry = _entry(setup_guestbook, entry_id)
    assert entry.correction.kind == "resident"
    assert entry.correction.source == "push"
    assert entry.open is False


async def test_answering_delivery_moves_the_entry_to_the_rings_calendar(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await answer(hass, action(setup_guestbook, "DELIVERY", entry_id))

    assert await get_visits(hass) == []
    (event,) = await get_rings(hass)
    assert event["summary"] == "Delivery"


async def test_answering_visit_uses_the_reply_text_as_the_guest_name(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await answer(hass, action(setup_guestbook, "VISIT", entry_id), reply_text="Grandma Kim")

    entry = _entry(setup_guestbook, entry_id)
    assert entry.correction.kind == "visit"
    assert entry.correction.guest_name == "Grandma Kim"
    assert entry.correction.source == "push"


async def test_answering_unknown_keeps_the_decision(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await answer(hass, action(setup_guestbook, "UNKNOWN", entry_id))

    entry = _entry(setup_guestbook, entry_id)
    assert entry.correction.kind == "unknown"
    assert entry.open is True


async def test_a_correction_by_push_fires_the_corrected_event(hass: HomeAssistant, setup_guestbook):
    events = []
    hass.bus.async_listen(EVENT_VISIT_CORRECTED, events.append)
    entry_id = await start_uncertain_visit(hass)

    await answer(hass, action(setup_guestbook, "DELIVERY", entry_id))

    assert [e.data for e in events] == [
        {
            "entry_id": entry_id,
            "kind": "delivery",
            "guest_name": None,
            "guests": [],
            "certainty": "uncertain",
            "start": "2026-10-21T14:00:00+00:00",
            "end": "2026-10-21T14:00:00+00:00",
        }
    ]


async def test_answers_for_unknown_entries_and_foreign_actions_are_ignored(
    hass: HomeAssistant, setup_guestbook, caplog
):
    entry_id = await start_uncertain_visit(hass)
    events = []
    hass.bus.async_listen(EVENT_VISIT_CORRECTED, events.append)

    await answer(hass, "GUESTBOOK_DELIVERY_0123456789abcdef0123456789abcdef_sometoken")
    await answer(hass, "ALARM")
    await answer(hass, "REPLY", reply_text="hello")
    await answer(hass, f"GUESTBOOK_COFFEE_{entry_id}_x")
    hass.bus.async_fire(ACTION_EVENT, {})
    await hass.async_block_till_done()

    assert events == []
    assert _entry(setup_guestbook, entry_id).correction is None
    assert "Traceback" not in caplog.text
    assert "ERROR" not in caplog.text


async def test_an_answer_to_a_ring_still_in_its_window_is_ignored(hass: HomeAssistant, setup_guestbook, caplog):
    await ring(hass)
    (pending,) = setup_guestbook.runtime_data.async_entries(EffectiveKind.PENDING_RING)

    await answer(hass, f"GUESTBOOK_DELIVERY_{pending.id}_sometoken")

    assert "ERROR" not in caplog.text
    assert pending.correction is None


async def test_answers_after_the_integration_was_unloaded_do_nothing(hass: HomeAssistant, setup_guestbook):
    events = []
    hass.bus.async_listen(EVENT_VISIT_CORRECTED, events.append)
    entry_id = await start_uncertain_visit(hass)
    button = action(setup_guestbook, "DELIVERY", entry_id)
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    await answer(hass, button)

    assert events == []


def _entry(config_entry, entry_id: str):
    return next(e for e in config_entry.runtime_data.async_entries(*EffectiveKind) if e.id == entry_id)


async def test_answers_with_a_wrong_missing_or_foreign_token_are_ignored(hass: HomeAssistant, setup_guestbook, caplog):
    entry_id = await start_uncertain_visit(hass)
    events = []
    hass.bus.async_listen(EVENT_VISIT_CORRECTED, events.append)

    await answer(hass, f"GUESTBOOK_RESIDENT_{entry_id}_wrongtoken")
    await answer(hass, f"GUESTBOOK_RESIDENT_{entry_id}")
    await answer(hass, f"GUESTBOOK_RESIDENT_{entry_id}_")

    assert events == []
    entry = _entry(setup_guestbook, entry_id)
    assert entry.correction is None
    assert entry.open is True
    assert entry.question_token  # still waiting for the right answer
    assert "ERROR" not in caplog.text


async def test_a_question_can_be_answered_only_once(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)
    first = action(setup_guestbook, "UNKNOWN", entry_id)
    second = first.replace("UNKNOWN", "DELIVERY")
    events = []
    hass.bus.async_listen(EVENT_VISIT_CORRECTED, events.append)

    await answer(hass, first)
    await answer(hass, second)
    await answer(hass, first)

    assert [e.data["kind"] for e in events] == ["unknown"]
    entry = _entry(setup_guestbook, entry_id)
    assert entry.correction.kind == "unknown"
    assert entry.question_token is None


async def test_a_token_of_another_entry_does_not_open_this_entry(hass: HomeAssistant, setup_guestbook, freezer):
    first_id = await start_uncertain_visit(hass)
    await advance(hass, freezer, timedelta(hours=4))
    await set_tracker(hass, DOOR, "off")
    second_id = await start_uncertain_visit(hass)
    assert first_id != second_id
    stolen = action(setup_guestbook, "RESIDENT", second_id).replace(second_id, first_id)

    await answer(hass, stolen)

    assert _entry(setup_guestbook, first_id).correction is None


async def test_the_token_survives_a_restart_and_is_not_exported(
    hass: HomeAssistant, setup_guestbook, hass_tmp_config_dir
):
    entry_id = await start_uncertain_visit(hass)
    token = _entry(setup_guestbook, entry_id).question_token
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    await hass.services.async_call("guestbook", "export", {}, blocking=True, return_response=True)
    exported = next(Path(hass_tmp_config_dir, "guestbook").glob("*.jsonl")).read_text()
    await answer(hass, f"GUESTBOOK_DELIVERY_{entry_id}_{token}")

    assert token not in exported
    assert _entry(setup_guestbook, entry_id).correction.kind == "delivery"


async def test_the_correct_entry_action_needs_no_token(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await hass.services.async_call(
        "guestbook", "correct_entry", {"entry_id": entry_id, "kind": "delivery"}, blocking=True
    )

    assert _entry(setup_guestbook, entry_id).correction.kind == "delivery"
