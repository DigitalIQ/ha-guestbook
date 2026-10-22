import json
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.core import HomeAssistant
from pytest_homeassistant_custom_component.common import async_mock_service

from custom_components.guestbook.const import CONF_NOTIFY_ENTITIES

from .conftest import (
    ALEX_PHONE,
    DOOR,
    add_guest,
    add_phone,
    advance,
    make_unanswered_ring,
    ring,
    set_options,
    set_tracker,
)

COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"
PATH = "/guestbook-dashboard/visits"
MESSENGER = "notify.family_messenger"


async def select_phone(hass: HomeAssistant, entry, name: str, os_name: str, **options) -> list:
    device_id = await add_phone(hass, name, os_name)
    await set_options(hass, entry, phones=[device_id], **options)
    return async_mock_service(hass, "notify", f"mobile_app_{name.casefold().replace(' ', '_')}")


async def start_uncertain_visit(hass: HomeAssistant) -> None:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()


# --- push_open_path ---------------------------------------------------------------------------------------------


@pytest.mark.parametrize(("os_name", "name"), [("iOS", "iPhone of Sam"), ("Android", "Pixel of Alex")])
async def test_every_push_to_a_phone_opens_the_dashboard_path(
    hass: HomeAssistant, setup_guestbook, freezer, os_name, name
):
    calls = await select_phone(
        hass, setup_guestbook, name, os_name, push_open_path=PATH, push_unanswered_ring=True, push_correction=False
    )
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")  # arrival
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))  # end
    await make_unanswered_ring(hass, freezer)  # unanswered ring

    assert [c.data["title"] for c in calls] == ["Visit", "Visit ended", "Unanswered ring"]
    for call in calls:
        assert call.data["data"] == {"url": PATH, "clickAction": PATH}


async def test_the_correction_question_keeps_its_buttons_next_to_the_path(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, "iPhone of Sam", "iOS", push_open_path=PATH, push_arrival=False)

    await start_uncertain_visit(hass)

    (call,) = calls
    data = call.data["data"]
    assert (data["url"], data["clickAction"]) == (PATH, PATH)
    assert data["tag"]
    assert [a["title"] for a in data["actions"]] == ["That was me", "Delivery", "Visit", "Don't know"]


async def test_a_phone_push_without_the_option_has_no_path(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, "Pixel of Alex", "Android", push_correction=False)
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")

    (call,) = calls
    assert "data" not in call.data


async def test_a_blank_path_counts_as_no_path(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(
        hass, setup_guestbook, "Pixel of Alex", "Android", push_open_path="  ", push_correction=False
    )
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")

    assert "data" not in calls[0].data


async def test_the_path_is_for_phones_not_for_text_only_targets(hass: HomeAssistant, setup_guestbook):
    send_message = async_mock_service(hass, "notify", "send_message")
    await select_phone(hass, setup_guestbook, "Pixel of Alex", "Android", push_open_path=PATH, push_correction=False)
    await set_options(hass, setup_guestbook, **{CONF_NOTIFY_ENTITIES: [MESSENGER]})
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")

    (call,) = send_message
    assert set(call.data) == {"entity_id", "title", "message"}


async def test_the_path_is_changed_in_the_options_without_a_reload(hass: HomeAssistant, setup_guestbook):
    device_id = await add_phone(hass, "Pixel of Alex", "Android")
    calls = async_mock_service(hass, "notify", "mobile_app_pixel_of_alex")
    await set_options(hass, setup_guestbook, phones=[device_id], push_open_path=PATH, push_correction=False)
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_options(hass, setup_guestbook, phones=[device_id], push_open_path="/lovelace/home", push_correction=False)

    await set_tracker(hass, ALEX_PHONE, "home")

    assert calls[0].data["data"] == {"url": "/lovelace/home", "clickAction": "/lovelace/home"}


# --- hint for iOS -----------------------------------------------------------------------------------------------


async def test_the_ios_question_asks_to_press_and_hold(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, "iPhone of Sam", "iOS", push_arrival=False)

    await start_uncertain_visit(hass)

    assert calls[0].data["message"] == (
        "Someone rang and came in. Was that you, a delivery or a visit? Press and hold to answer."
    )


async def test_the_ios_hint_follows_the_language(hass: HomeAssistant, setup_guestbook):
    hass.config.language = "de"
    calls = await select_phone(hass, setup_guestbook, "iPhone of Sam", "iOS", push_arrival=False)

    await start_uncertain_visit(hass)

    assert calls[0].data["message"].endswith(" Zum Antworten lange drücken.")


async def test_the_android_question_has_no_hint(hass: HomeAssistant, setup_guestbook):
    calls = await select_phone(hass, setup_guestbook, "Pixel of Alex", "Android", push_arrival=False)

    await start_uncertain_visit(hass)

    assert calls[0].data["message"] == "Someone rang and came in. Was that you, a delivery or a visit?"


async def test_the_text_only_question_has_no_hint(hass: HomeAssistant, setup_guestbook):
    send_message = async_mock_service(hass, "notify", "send_message")
    await set_options(hass, setup_guestbook, **{CONF_NOTIFY_ENTITIES: [MESSENGER]}, push_arrival=False)

    await start_uncertain_visit(hass)

    assert "hold" not in send_message[0].data["message"]


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_option_is_translated(language):
    pushes = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())["options"]["step"]["pushes"]

    assert pushes["data"]["push_open_path"]
    assert pushes["data_description"]["push_open_path"]
