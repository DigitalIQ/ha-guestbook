import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import device_registry as dr
from pytest_homeassistant_custom_component.common import async_capture_events, async_mock_service

from custom_components.guestbook.const import CONF_RESIDENTS
from custom_components.guestbook.core import EffectiveKind

from .conftest import ALEX_PHONE, add_guest, add_phone, advance, ring, set_options, set_tracker

PIXEL_SERVICE = "mobile_app_pixel_of_alex"
MESSENGER = "notify.family_messenger"


async def start_guest_visit(hass: HomeAssistant, entry) -> None:
    await add_guest(hass, entry, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")


async def end_guest_visit(hass: HomeAssistant, freezer) -> None:
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))


async def select_targets(hass: HomeAssistant, entry, **options) -> list:
    """Select the phone and the messenger and return the calls of the phone service."""
    device_id = await add_phone(hass)
    await set_options(hass, entry, phones=[device_id], **options)
    return async_mock_service(hass, "notify", PIXEL_SERVICE)


async def test_options_form_offers_the_push_targets_and_switches(hass: HomeAssistant, setup_guestbook):
    result = await hass.config_entries.options.async_init(setup_guestbook.entry_id)

    assert result["type"] is FlowResultType.FORM
    schema = result["data_schema"].schema
    assert {str(key) for key in schema} == {
        "phones",
        "notify_entities",
        "push_arrival",
        "push_end",
        "push_correction",
        "push_unanswered_ring",
    }
    keys = {str(key): key for key in schema}
    assert schema[keys["phones"]].config["integration"] == "mobile_app"
    assert schema[keys["phones"]].config["multiple"] is True
    assert schema[keys["notify_entities"]].config["domain"] == ["notify"]


async def test_push_switches_default_to_arrival_end_correction_on_and_unanswered_ring_off(
    hass: HomeAssistant, setup_guestbook
):
    await set_options(hass, setup_guestbook)

    assert setup_guestbook.options == {
        "phones": [],
        "notify_entities": [],
        "push_arrival": True,
        "push_end": True,
        "push_correction": True,
        "push_unanswered_ring": False,
    }


async def test_changing_options_keeps_open_visits_and_applies_at_once(hass: HomeAssistant, setup_guestbook):
    await start_guest_visit(hass, setup_guestbook)
    runtime = setup_guestbook.runtime_data

    calls = await select_targets(hass, setup_guestbook)

    assert setup_guestbook.runtime_data is runtime
    assert hass.states.get("binary_sensor.guestbook_visit_active").state == "on"
    assert calls == []


async def test_arrival_push_goes_to_the_phone_and_the_notify_entity_with_the_entry_id(
    hass: HomeAssistant, setup_guestbook
):
    calls = await select_targets(hass, setup_guestbook, notify_entities=[MESSENGER])
    messenger = async_mock_service(hass, "notify", "send_message")

    await start_guest_visit(hass, setup_guestbook)

    (call,) = calls
    assert call.data == {"title": "Visit", "message": "Arrived: Alex."}
    (message,) = messenger
    entry_id = setup_guestbook.runtime_data.async_open_visits()[0].id
    assert message.data == {
        "entity_id": [MESSENGER],
        "title": "Visit",
        "message": f"Arrived: Alex. Entry id: {entry_id}",
    }


async def test_phone_already_home_at_startup_sends_no_arrival_push_but_fires_the_event(
    hass: HomeAssistant, setup_guestbook, hass_storage
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    calls = await select_targets(hass, setup_guestbook)
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass_storage["guestbook.entries"]["data"]["entries"].clear()
    hass.states.async_set(ALEX_PHONE, "home")
    started = async_capture_events(hass, "guestbook_visit_started")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert calls == []
    assert [e.data["guests"] for e in started] == [["Alex"]]


async def test_arrival_push_uses_the_home_assistant_language(hass: HomeAssistant, setup_guestbook):
    hass.config.language = "de"
    calls = await select_targets(hass, setup_guestbook)

    await start_guest_visit(hass, setup_guestbook)

    assert calls[0].data == {"title": "Besuch", "message": "Angekommen: Alex."}


async def test_arrival_push_only_when_no_selected_resident_is_home(hass: HomeAssistant, setup_guestbook, freezer):
    hass.states.async_set("person.sam", "not_home")
    hass.states.async_set("person.kim", "home")
    hass.config_entries.async_update_entry(
        setup_guestbook, data={**setup_guestbook.data, CONF_RESIDENTS: ["person.sam", "person.kim"]}
    )
    calls = await select_targets(hass, setup_guestbook, push_correction=False)
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")
    assert calls == []

    await end_guest_visit(hass, freezer)
    assert calls == []

    hass.states.async_set("person.kim", "not_home")
    await set_tracker(hass, ALEX_PHONE, "home")
    assert [c.data["title"] for c in calls] == ["Visit"]


async def test_arrival_push_can_be_switched_off(hass: HomeAssistant, setup_guestbook):
    calls = await select_targets(hass, setup_guestbook, push_arrival=False)

    await start_guest_visit(hass, setup_guestbook)

    assert calls == []


async def test_end_push_names_the_guests(hass: HomeAssistant, setup_guestbook, freezer):
    calls = await select_targets(hass, setup_guestbook)
    await start_guest_visit(hass, setup_guestbook)

    await end_guest_visit(hass, freezer)

    assert [c.data for c in calls] == [
        {"title": "Visit", "message": "Arrived: Alex."},
        {"title": "Visit ended", "message": "Left: Alex."},
    ]


async def test_end_push_is_suppressed_when_a_resident_is_home_or_the_switch_is_off(
    hass: HomeAssistant, setup_guestbook, freezer
):
    hass.states.async_set("person.sam", "home")
    hass.config_entries.async_update_entry(
        setup_guestbook, data={**setup_guestbook.data, CONF_RESIDENTS: ["person.sam"]}
    )
    calls = await select_targets(hass, setup_guestbook)
    await start_guest_visit(hass, setup_guestbook)
    await end_guest_visit(hass, freezer)
    assert calls == []

    hass.states.async_set("person.sam", "not_home")
    await set_options(hass, setup_guestbook, phones=setup_guestbook.options["phones"], push_end=False)
    await set_tracker(hass, ALEX_PHONE, "home")
    await end_guest_visit(hass, freezer)
    assert [c.data["title"] for c in calls] == ["Visit"]


async def test_no_end_push_when_a_correction_closes_the_visit(hass: HomeAssistant, setup_guestbook, freezer):
    calls = await select_targets(hass, setup_guestbook, push_correction=False)
    await ring(hass)
    hass.states.async_set("binary_sensor.front_door", "on")
    await hass.async_block_till_done()
    runtime = setup_guestbook.runtime_data
    (visit,) = runtime.async_open_visits()

    runtime.async_correct_entry(visit.id, "delivery")

    assert [c.data["title"] for c in calls] == ["Visit"]


async def test_unanswered_ring_push_is_off_by_default_and_can_be_switched_on(
    hass: HomeAssistant, setup_guestbook, freezer
):
    calls = await select_targets(hass, setup_guestbook)
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))
    assert calls == []

    await set_options(hass, setup_guestbook, phones=setup_guestbook.options["phones"], push_unanswered_ring=True)
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    (call,) = calls
    assert call.data["title"] == "Unanswered ring"


async def test_unanswered_ring_push_to_a_notify_entity_carries_the_entry_id(
    hass: HomeAssistant, setup_guestbook, freezer
):
    messenger = async_mock_service(hass, "notify", "send_message")
    await set_options(hass, setup_guestbook, notify_entities=[MESSENGER], push_unanswered_ring=True)

    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))

    (message,) = messenger
    (entry,) = setup_guestbook.runtime_data.async_entries(EffectiveKind.UNANSWERED_RING)
    assert message.data["message"].endswith(f"Entry id: {entry.id}")


async def test_a_phone_without_its_notify_service_is_skipped_and_the_others_still_get_the_push(
    hass: HomeAssistant, setup_guestbook, caplog
):
    caplog.set_level(logging.DEBUG, logger="custom_components.guestbook")
    device_id = await add_phone(hass)
    await set_options(hass, setup_guestbook, phones=[device_id], notify_entities=[MESSENGER])
    messenger = async_mock_service(hass, "notify", "send_message")

    await start_guest_visit(hass, setup_guestbook)

    assert len(messenger) == 1
    assert "notify.mobile_app_pixel_of_alex" in caplog.text


async def test_a_selected_device_that_is_no_longer_a_phone_is_skipped(hass: HomeAssistant, setup_guestbook):
    await set_options(hass, setup_guestbook, phones=["0123456789abcdef0123456789abcdef"])
    messenger = async_mock_service(hass, "notify", "send_message")

    await start_guest_visit(hass, setup_guestbook)

    assert messenger == []


async def test_a_renamed_phone_device_still_finds_its_notify_service(hass: HomeAssistant, setup_guestbook):
    calls = await select_targets(hass, setup_guestbook)
    dr.async_get(hass).async_update_device(setup_guestbook.options["phones"][0], name_by_user="Alex's work phone")

    await start_guest_visit(hass, setup_guestbook)

    assert [c.data["title"] for c in calls] == ["Visit"]
