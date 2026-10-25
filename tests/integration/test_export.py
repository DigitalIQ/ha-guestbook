import json
from pathlib import Path

import pytest
from homeassistant.core import Context, HomeAssistant
from homeassistant.exceptions import Unauthorized

from custom_components.guestbook.const import DOMAIN
from custom_components.guestbook.core import EffectiveKind

from .conftest import make_unanswered_ring, make_visit, ring


@pytest.fixture
def hass_config_dir(hass_tmp_config_dir: str) -> str:
    return hass_tmp_config_dir


async def export(hass: HomeAssistant, **data) -> dict:
    return await hass.services.async_call(DOMAIN, "export", data, blocking=True, return_response=True)


async def test_export_is_refused_for_a_user_who_is_not_an_admin(
    hass: HomeAssistant, setup_guestbook, hass_read_only_user, hass_config_dir
):
    with pytest.raises(Unauthorized):
        await hass.services.async_call(
            DOMAIN, "export", {}, blocking=True, return_response=True, context=Context(user_id=hass_read_only_user.id)
        )

    assert not Path(hass_config_dir, "guestbook").exists()


def read_lines(path: str) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text().splitlines()]


async def test_export_writes_one_json_line_per_entry_sorted_by_start(
    hass: HomeAssistant, setup_guestbook, freezer, hass_config_dir
):
    visit_id = await make_visit(hass, freezer)
    ring_id = await make_unanswered_ring(hass, freezer)

    result = await export(hass)

    assert result == {"path": f"{hass_config_dir}/guestbook/guestbook-20261021T180600Z.jsonl", "count": 2}
    lines = read_lines(result["path"])
    assert [line["id"] for line in lines] == [visit_id, ring_id]
    visit = lines[0]
    assert visit["kind"] == "visit"
    assert visit["reason"]["code"] == "ring_then_door"
    assert [s["kind"] for s in visit["signals"]] == ["ring", "door_open"]
    assert visit["settings"]["ring_window"] == 300.0
    assert visit["correction"] is None
    assert lines[1]["kind"] == "unanswered_ring"


async def test_export_contains_corrections_and_notes(hass: HomeAssistant, setup_guestbook, freezer):
    entry_id = await make_visit(hass, freezer)
    await hass.services.async_call(
        DOMAIN, "correct_entry", {"entry_id": entry_id, "kind": "visit", "guest_name": "Alex"}, blocking=True
    )
    await hass.services.async_call(DOMAIN, "add_note", {"entry_id": entry_id, "note": "Brought cake"}, blocking=True)

    (line,) = read_lines((await export(hass))["path"])

    assert line["correction"]["kind"] == "visit"
    assert line["correction"]["guest_name"] == "Alex"
    assert line["notes"] == ["Brought cake"]


async def test_export_range_limits_the_entries_by_their_start(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    ring_id = await make_unanswered_ring(hass, freezer)

    later = await export(hass, start="2026-10-21T15:00:00+00:00")
    earlier = await export(hass, end="2026-10-21T15:00:00+00:00")
    none = await export(hass, start="2026-10-22T00:00:00+00:00")

    assert [line["id"] for line in read_lines(later["path"])] == [ring_id]
    assert earlier["count"] == 1
    assert none["count"] == 0
    assert Path(none["path"]).read_text() == ""


async def test_export_without_a_response_still_writes_the_file(
    hass: HomeAssistant, setup_guestbook, freezer, hass_config_dir
):
    await make_visit(hass, freezer)

    await hass.services.async_call(DOMAIN, "export", {}, blocking=True)

    (file,) = Path(hass_config_dir, "guestbook").glob("guestbook-*.jsonl")
    assert len(file.read_text().splitlines()) == 1


async def test_export_leaves_out_pending_rings_and_the_rule_state(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    await ring(hass)
    assert len(setup_guestbook.runtime_data.async_entries(EffectiveKind.PENDING_RING)) == 1

    result = await export(hass)

    assert result["count"] == 1
    (line,) = read_lines(result["path"])
    assert line["kind"] == "visit"
    assert "rule_state" not in line


async def test_export_names_the_button_as_the_source_of_a_correction(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    await hass.services.async_call("button", "press", {"entity_id": "button.guestbook_that_was_me"}, blocking=True)

    (line,) = read_lines((await export(hass))["path"])

    assert line["correction"]["kind"] == "resident"
    assert line["correction"]["source"] == "button"
