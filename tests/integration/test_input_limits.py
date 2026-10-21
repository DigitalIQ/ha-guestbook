import asyncio
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import probatio
import pytest
from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from custom_components.guestbook.const import DOMAIN
from custom_components.guestbook.core import Certainty, Entry, EntryKind

from .conftest import ALEX_PHONE, DOOR, add_guest, advance, get_visits, make_visit, ring, set_options, set_tracker

ACTION_EVENT = "mobile_app_notification_action"
LONG = "L" * 100
CUT = "L" * 64


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


async def open_visit(hass: HomeAssistant) -> str:
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    return hass.states.get("sensor.guestbook_current_visit").attributes["entry_id"]


# --- stored entries that break the rules of the engine ---------------------------------------------------------------


@pytest.mark.parametrize(
    "rule_state",
    [{}, {"deadline": None}, {"deadline": "soon"}, {"deadline": "2026-10-21T14:05:00"}],
    ids=["missing", "none", "garbage", "naive"],
)
async def test_stored_pending_ring_without_a_usable_deadline_does_not_block_the_setup(
    hass: HomeAssistant, setup_guestbook, hass_storage, caplog, rule_state
):
    good = Entry(
        id="good",
        kind=EntryKind.VISIT,
        start=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 21, 11, 0, tzinfo=UTC),
        certainty=Certainty.CERTAIN,
        guests=[{"id": "", "name": "Alex"}],
    )
    ring_entry = Entry(
        id="ring", kind=EntryKind.PENDING_RING, start=datetime(2026, 10, 21, 13, 59, tzinfo=UTC), rule_state=rule_state
    )
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass_storage["guestbook.entries"] = {
        "version": 1,
        "minor_version": 1,
        "key": "guestbook.entries",
        "data": {"entries": [good.to_dict(), ring_entry.to_dict()]},
    }

    with caplog.at_level(logging.WARNING):
        assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
        await hass.async_block_till_done()

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Alex"]
    assert any("deadline" in r.getMessage() for r in caplog.records if r.levelno == logging.WARNING)


# --- export files -------------------------------------------------------------------------------------------------


async def test_an_export_never_overwrites_a_file_even_if_the_name_looks_free(
    hass: HomeAssistant, setup_guestbook, freezer, hass_config_dir
):
    await make_visit(hass, freezer)
    first = await hass.services.async_call(DOMAIN, "export", {}, blocking=True, return_response=True)
    first_text = Path(first["path"]).read_text()
    await ring(hass)
    await hass.async_block_till_done()

    with patch.object(Path, "exists", return_value=False):  # another export just took the name
        second = await hass.services.async_call(DOMAIN, "export", {}, blocking=True, return_response=True)

    assert second["path"] != first["path"]
    assert Path(first["path"]).read_text() == first_text
    assert Path(second["path"]).exists()


async def test_exports_in_the_same_second_run_side_by_side_without_overwriting(
    hass: HomeAssistant, setup_guestbook, freezer, hass_config_dir
):
    await make_visit(hass, freezer)

    results = await asyncio.gather(
        *(hass.services.async_call(DOMAIN, "export", {}, blocking=True, return_response=True) for _ in range(5))
    )

    assert len({r["path"] for r in results}) == 5
    assert len(list(Path(hass_config_dir, "guestbook").glob("guestbook-*.jsonl"))) == 5


# --- guest names ---------------------------------------------------------------------------------------------------


async def test_correct_entry_cuts_and_trims_the_guest_name(hass: HomeAssistant, setup_guestbook):
    entry_id = await open_visit(hass)

    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": "visit", "guest_name": f"  {LONG}  "}, blocking=True
    )

    assert setup_guestbook.runtime_data.async_get_entry(entry_id).correction.guest_name == CUT


async def test_a_push_reply_is_cut_to_the_maximum_length(hass: HomeAssistant, setup_guestbook):
    entry_id = await open_visit(hass)
    token = setup_guestbook.runtime_data.async_get_entry(entry_id).question_token

    hass.bus.async_fire(ACTION_EVENT, {"action": f"GUESTBOOK_VISIT_{entry_id}_{token}", "reply_text": LONG})
    await hass.async_block_till_done()

    assert setup_guestbook.runtime_data.async_get_entry(entry_id).correction.guest_name == CUT


async def test_add_visit_cuts_long_guest_names(hass: HomeAssistant, setup_guestbook):
    await hass.services.async_call(
        DOMAIN,
        "add_visit",
        {"guests": [LONG, " Pat "], "start": "2026-10-21T10:00:00+00:00", "end": "2026-10-21T11:00:00+00:00"},
        blocking=True,
    )

    (event,) = await get_visits(hass)
    assert event["summary"] == f"Visit: {CUT}, Pat"


async def test_guest_profile_names_are_cut_in_the_form(hass: HomeAssistant, setup_guestbook):
    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "user"}
    )
    await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": f" {LONG} ", "trackers": [ALEX_PHONE]}
    )

    (subentry,) = setup_guestbook.subentries.values()
    assert subentry.title == CUT
    assert subentry.data["name"] == CUT


async def test_the_current_visit_state_stays_below_255_characters(hass: HomeAssistant, setup_guestbook):
    names = {f"{letter}" * 64: f"device_tracker.guest_{letter}" for letter in "ABCDE"}
    for name, tracker in names.items():
        await add_guest(hass, setup_guestbook, name, [tracker])
    for tracker in names.values():
        await set_tracker(hass, tracker, "home")

    state = hass.states.get("sensor.guestbook_current_visit")

    assert len(state.state) <= 250
    assert state.state.endswith("…")
    assert state.state.startswith("A" * 64 + ", " + "B" * 64)
    assert len(await get_visits(hass)) == 1


async def test_a_short_guest_list_is_not_cut(hass: HomeAssistant, setup_guestbook):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    assert hass.states.get("sensor.guestbook_current_visit").state == "Alex"


# --- add_visit input -------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("guests", [[{"a": 1}], [None], [["x"]], [""], ["  "], "", [" Alex ", ""]])
async def test_add_visit_rejects_guests_that_are_not_non_empty_strings(hass: HomeAssistant, setup_guestbook, guests):
    with pytest.raises(probatio.Invalid):
        await hass.services.async_call(
            DOMAIN,
            "add_visit",
            {"guests": guests, "start": "2026-10-21T10:00:00+00:00", "end": "2026-10-21T11:00:00+00:00"},
            blocking=True,
        )

    assert await get_visits(hass) == []


async def test_add_visit_turns_a_number_into_a_name_and_accepts_a_single_name(hass: HomeAssistant, setup_guestbook):
    for guests in ([17], "Pat"):
        await hass.services.async_call(
            DOMAIN,
            "add_visit",
            {"guests": guests, "start": "2026-10-21T10:00:00+00:00", "end": "2026-10-21T11:00:00+00:00"},
            blocking=True,
        )

    assert sorted(e["summary"] for e in await get_visits(hass)) == ["Visit: 17", "Visit: Pat"]


# --- guest suggestions of purged visits -------------------------------------------------------------------------------


async def test_purging_a_visit_removes_its_guest_suggestion(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", retention=30)
    purged = await make_visit(hass, freezer)
    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": purged, "kind": "visit", "guest_name": "Robin"}, blocking=True
    )
    await advance(hass, freezer, timedelta(days=2))
    await set_tracker(hass, DOOR, "off")
    kept = await make_visit(hass, freezer)
    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": kept, "kind": "visit", "guest_name": "Kim"}, blocking=True
    )
    registry = ir.async_get(hass)
    assert registry.async_get_issue(DOMAIN, "guest_suggestion_robin")
    assert registry.async_get_issue(DOMAIN, "guest_suggestion_kim")

    await advance(hass, freezer, timedelta(days=29))

    assert setup_guestbook.runtime_data.async_get_entry(purged) is None
    assert registry.async_get_issue(DOMAIN, "guest_suggestion_robin") is None
    assert registry.async_get_issue(DOMAIN, "guest_suggestion_kim")


async def test_a_suggestion_whose_visit_was_purged_while_the_integration_was_off_is_removed_at_startup(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    entry_id = await make_visit(hass, freezer)
    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": "visit", "guest_name": "Robin"}, blocking=True
    )
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass_storage["guestbook.entries"]["data"]["entries"].clear()

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert ir.async_get(hass).async_get_issue(DOMAIN, "guest_suggestion_robin") is None
