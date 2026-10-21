import json
from pathlib import Path
from types import MappingProxyType

import pytest
from homeassistant.components.repairs import DOMAIN as REPAIRS_DOMAIN
from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import issue_registry as ir
from homeassistant.setup import async_setup_component

from custom_components.guestbook.const import CONF_RESIDENTS, DOMAIN

from .conftest import ALEX_PHONE, DOOR, RESIDENT_PHONE, add_guest, make_visit, ring, set_tracker

ACTION_EVENT = "mobile_app_notification_action"
COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"
ROBIN_ISSUE = "guest_suggestion_robin"
ROBIN_PHONE = "device_tracker.robin_phone"
NEIGHBOUR_PHONE = "device_tracker.neighbour_phone"


def issue(hass: HomeAssistant, issue_id: str = ROBIN_ISSUE) -> ir.IssueEntry | None:
    return ir.async_get(hass).async_get_issue(DOMAIN, issue_id)


def guest_issues(hass: HomeAssistant) -> set[str]:
    return {i for d, i in ir.async_get(hass).issues if d == DOMAIN and i.startswith("guest_suggestion_")}


async def correct(hass: HomeAssistant, entry_id: str, kind: str = "visit", **data) -> None:
    await hass.services.async_call(DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": kind, **data}, blocking=True)


async def start_uncertain_visit(hass: HomeAssistant) -> str:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    return hass.states.get("sensor.guestbook_current_visit").attributes["entry_id"]


@pytest.fixture
async def flows(hass: HomeAssistant):
    assert await async_setup_component(hass, "repairs", {})
    return hass.data[REPAIRS_DOMAIN]["flow_manager"]


async def test_correction_with_an_unknown_guest_raises_a_fixable_issue(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    await correct(hass, entry_id, guest_name="Robin")

    found = issue(hass)
    assert found.is_fixable is True
    assert found.translation_key == "guest_suggestion"
    assert found.translation_placeholders == {"name": "Robin"}
    assert found.data == {"entry_id": setup_guestbook.entry_id, "name": "Robin", "visit_id": entry_id}


async def test_answer_by_push_raises_the_issue_too(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)

    hass.bus.async_fire(ACTION_EVENT, {"action": f"GUESTBOOK_VISIT_{entry_id}", "reply_text": "Robin"})
    await hass.async_block_till_done()

    assert issue(hass).data["name"] == "Robin"


async def test_the_same_name_in_any_case_is_one_issue(hass: HomeAssistant, setup_guestbook, freezer):
    first = await start_uncertain_visit(hass)
    await correct(hass, first, guest_name="Robin")
    second = await make_visit(hass, freezer)

    await correct(hass, second, guest_name="robin")

    assert guest_issues(hass) == {ROBIN_ISSUE}
    assert issue(hass).data["visit_id"] == second


@pytest.mark.parametrize("name", ["Alex", "alex", " ALEX "])
async def test_no_issue_for_a_guest_that_has_a_profile(hass: HomeAssistant, setup_guestbook, name):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    entry_id = await start_uncertain_visit(hass)

    await correct(hass, entry_id, guest_name=name)

    assert guest_issues(hass) == set()


@pytest.mark.parametrize(("kind", "data"), [("visit", {}), ("delivery", {"guest_name": "Robin"}), ("unknown", {})])
async def test_no_issue_without_a_guest_name_for_a_visit(hass: HomeAssistant, setup_guestbook, kind, data):
    entry_id = await start_uncertain_visit(hass)

    await correct(hass, entry_id, kind, **data)

    assert guest_issues(hass) == set()


async def test_issue_disappears_when_a_guest_with_that_name_exists(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")
    assert issue(hass) is not None

    await add_guest(hass, setup_guestbook, "robin", [ROBIN_PHONE])

    assert guest_issues(hass) == set()


async def test_issue_stays_while_another_guest_is_added(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")

    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    assert guest_issues(hass) == {ROBIN_ISSUE}


async def test_fix_flow_shows_the_name_and_preselects_unlinked_phones_that_are_home(
    hass: HomeAssistant, setup_guestbook, flows
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    hass.config_entries.async_update_entry(
        setup_guestbook, data={**setup_guestbook.data, CONF_RESIDENTS: ["person.sam"]}
    )
    hass.states.async_set("person.sam", "home", {"device_trackers": [RESIDENT_PHONE]})
    for tracker, state in (
        (ALEX_PHONE, "home"),
        (RESIDENT_PHONE, "home"),
        (ROBIN_PHONE, "home"),
        (NEIGHBOUR_PHONE, "not_home"),
    ):
        hass.states.async_set(tracker, state)
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")

    result = await flows.async_init(DOMAIN, context={"issue_id": ROBIN_ISSUE})

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "guest"
    assert result["description_placeholders"] == {"name": "Robin"}
    (key,) = result["data_schema"].schema
    assert key.description["suggested_value"] == [ROBIN_PHONE]


async def test_fix_flow_creates_the_guest_with_the_selected_phones(hass: HomeAssistant, setup_guestbook, flows):
    hass.states.async_set(ROBIN_PHONE, "not_home")
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")
    result = await flows.async_init(DOMAIN, context={"issue_id": ROBIN_ISSUE})

    result = await flows.async_configure(result["flow_id"], {"trackers": [ROBIN_PHONE]})
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = setup_guestbook.subentries.values()
    assert (subentry.subentry_type, subentry.title) == ("guest", "Robin")
    assert dict(subentry.data) == {"name": "Robin", "trackers": [ROBIN_PHONE]}
    assert guest_issues(hass) == set()
    await set_tracker(hass, ROBIN_PHONE, "home")
    assert hass.states.get("binary_sensor.robin_visiting").state == "on"


async def test_fix_flow_can_create_a_guest_without_phones(hass: HomeAssistant, setup_guestbook, flows):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")
    result = await flows.async_init(DOMAIN, context={"issue_id": ROBIN_ISSUE})
    assert result["data_schema"].schema

    result = await flows.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    (subentry,) = setup_guestbook.subentries.values()
    assert dict(subentry.data) == {"name": "Robin", "trackers": []}


async def test_fix_flow_aborts_when_guestbook_is_not_loaded(hass: HomeAssistant, setup_guestbook, flows):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    result = await flows.async_init(DOMAIN, context={"issue_id": ROBIN_ISSUE})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "not_loaded"
    assert issue(hass) is not None


async def test_issue_for_a_guest_added_while_guestbook_was_unloaded_is_removed_at_startup(
    hass: HomeAssistant, setup_guestbook
):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    assert issue(hass) is not None
    subentry = ConfigSubentry(
        data=MappingProxyType({"name": "Robin", "trackers": []}),
        subentry_type="guest",
        title="Robin",
        unique_id=None,
    )
    hass.config_entries.async_add_subentry(setup_guestbook, subentry)

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert guest_issues(hass) == set()


async def test_removing_the_entry_removes_its_issues(hass: HomeAssistant, setup_guestbook):
    entry_id = await start_uncertain_visit(hass)
    await correct(hass, entry_id, guest_name="Robin")

    assert await hass.config_entries.async_remove(setup_guestbook.entry_id)

    assert guest_issues(hass) == set()


def test_suggestion_texts_exist_in_every_language():
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        issue_texts = json.loads((COMPONENT / name).read_text())["issues"]["guest_suggestion"]
        assert "{name}" in issue_texts["title"]
        assert "{name}" in issue_texts["description"]
        form = issue_texts["fix_flow"]["step"]["guest"]
        assert "{name}" in form["title"]
        assert form["data"]["trackers"]
        assert issue_texts["fix_flow"]["abort"]["not_loaded"]
