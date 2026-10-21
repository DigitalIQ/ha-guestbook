import json
from datetime import timedelta
from pathlib import Path

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import issue_registry as ir

from custom_components.guestbook.const import DOMAIN
from custom_components.guestbook.repairs import MISSING_SOURCE

from .conftest import DOOR, DOORBELL, PRESENCE, advance, get_visits, ring, set_options

COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"
GARAGE = "binary_sensor.garage_door"
ACTIVE = "binary_sensor.guestbook_visit_active"


def issue_ids(hass: HomeAssistant) -> set[str]:
    return {issue_id for domain, issue_id in ir.async_get(hass).issues if domain == DOMAIN}


async def select_sources(hass: HomeAssistant, entry, *doors: str) -> None:
    await set_options(
        hass, entry, step="sources", doorbells=[DOORBELL], doors=list(doors), presence=[PRESENCE], locks=[]
    )


async def test_no_issue_while_every_source_exists(hass: HomeAssistant, setup_guestbook):
    assert issue_ids(hass) == set()


async def test_missing_source_raises_one_issue_with_the_entity_id(hass: HomeAssistant, setup_guestbook):
    await select_sources(hass, setup_guestbook, DOOR, GARAGE)

    assert issue_ids(hass) == {f"missing_source_{GARAGE}"}
    issue = ir.async_get(hass).async_get_issue(DOMAIN, f"missing_source_{GARAGE}")
    assert issue.translation_key == "missing_source"
    assert issue.translation_placeholders == {"entity_id": GARAGE}
    assert issue.is_fixable is False
    assert issue.severity is ir.IssueSeverity.WARNING


async def test_issue_is_removed_when_the_entity_is_back(hass: HomeAssistant, setup_guestbook):
    await select_sources(hass, setup_guestbook, DOOR, GARAGE)

    hass.states.async_set(GARAGE, "off")
    await hass.async_block_till_done()

    assert issue_ids(hass) == set()


async def test_issue_returns_when_the_entity_disappears_again(hass: HomeAssistant, setup_guestbook):
    await select_sources(hass, setup_guestbook, DOOR)

    hass.states.async_remove(DOOR)
    await hass.async_block_till_done()

    assert issue_ids(hass) == {f"missing_source_{DOOR}"}


async def test_issue_is_removed_when_the_source_is_deselected(hass: HomeAssistant, setup_guestbook):
    await select_sources(hass, setup_guestbook, DOOR, GARAGE)

    await select_sources(hass, setup_guestbook, DOOR)

    assert issue_ids(hass) == set()


async def test_entity_in_the_registry_without_a_state_is_not_missing(hass: HomeAssistant, setup_guestbook):
    er.async_get(hass).async_get_or_create("binary_sensor", "test", "garage", suggested_object_id="garage_door")

    await select_sources(hass, setup_guestbook, DOOR, GARAGE)

    assert hass.states.get(GARAGE) is None
    assert issue_ids(hass) == set()


async def test_sources_missing_at_startup_raise_issues(hass: HomeAssistant, setup_guestbook):
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass.states.async_remove(DOOR)
    hass.states.async_remove(PRESENCE)

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    assert issue_ids(hass) == {f"missing_source_{DOOR}", f"missing_source_{PRESENCE}"}


async def test_one_issue_per_entity_even_when_selected_twice(hass: HomeAssistant, setup_guestbook):
    await set_options(hass, setup_guestbook, step="sources", doorbells=[GARAGE], doors=[GARAGE], presence=[], locks=[])

    assert issue_ids(hass) == {f"missing_source_{GARAGE}"}


async def test_issues_go_away_when_the_integration_is_unloaded(hass: HomeAssistant, setup_guestbook):
    await select_sources(hass, setup_guestbook, DOOR, GARAGE)

    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)

    assert issue_ids(hass) == set()


async def test_missing_and_unavailable_sources_do_not_stop_the_others(hass: HomeAssistant, setup_guestbook, freezer):
    await select_sources(hass, setup_guestbook, DOOR, GARAGE)
    hass.states.async_set(DOOR, "unavailable")
    await hass.async_block_till_done()

    await ring(hass)
    hass.states.async_set(PRESENCE, "on")
    await hass.async_block_till_done()

    assert hass.states.get(ACTIVE).state == "on"
    await advance(hass, freezer, timedelta(hours=4))
    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit (uncertain)"


def test_issue_texts_exist_in_every_language():
    for name in ("strings.json", "translations/en.json", "translations/de.json"):
        issue = json.loads((COMPONENT / name).read_text())["issues"][MISSING_SOURCE]
        assert issue["title"]
        assert "{entity_id}" in issue["description"]
