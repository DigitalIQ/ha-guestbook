import json
from pathlib import Path

import pytest
import yaml
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ServiceValidationError

from custom_components.guestbook.const import DOMAIN

from .conftest import get_rings, get_visits, make_unanswered_ring, make_visit, ring

COMPONENT = Path(__file__).parents[2] / "custom_components" / "guestbook"


async def test_correct_entry_without_an_id_corrects_the_latest_visit(hass: HomeAssistant, setup_guestbook, freezer):
    older = await make_visit(hass, freezer)

    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "delivery"}, blocking=True)

    assert setup_guestbook.runtime_data.async_get_entry(older).correction.kind == "delivery"
    assert await get_visits(hass) == []
    (event,) = await get_rings(hass)
    assert event["summary"] == "Delivery"


async def test_correct_entry_without_an_id_picks_the_most_recent_start(hass: HomeAssistant, setup_guestbook, freezer):
    first = await make_visit(hass, freezer)
    ring_id = await make_unanswered_ring(hass, freezer)

    response = await hass.services.async_call(
        DOMAIN, "correct_entry", {"kind": "visit", "guest_name": "Alex"}, blocking=True, return_response=True
    )

    assert response["entry_id"] == ring_id
    assert response["guests"] == ["Alex"]
    assert setup_guestbook.runtime_data.async_get_entry(first).correction is None


async def test_correct_entry_without_an_id_ignores_pending_rings(hass: HomeAssistant, setup_guestbook, freezer):
    visit_id = await make_visit(hass, freezer)
    await ring(hass)  # a pending ring is newer, but it cannot be corrected yet

    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "resident"}, blocking=True)

    assert setup_guestbook.runtime_data.async_get_entry(visit_id).correction.kind == "resident"


async def test_the_latest_entry_can_be_corrected_again(hass: HomeAssistant, setup_guestbook, freezer):
    visit_id = await make_visit(hass, freezer)

    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "resident"}, blocking=True)
    await hass.services.async_call(DOMAIN, "correct_entry", {"kind": "visit", "guest_name": "Sam"}, blocking=True)

    assert setup_guestbook.runtime_data.async_get_entry(visit_id).correction.guest_name == "Sam"
    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Sam"


async def test_add_note_without_an_id_notes_the_latest_entry(hass: HomeAssistant, setup_guestbook, freezer):
    await make_visit(hass, freezer)
    ring_id = await make_unanswered_ring(hass, freezer)

    await hass.services.async_call(DOMAIN, "add_note", {"note": "Probably the postman"}, blocking=True)

    assert setup_guestbook.runtime_data.async_get_entry(ring_id).notes == ["Probably the postman"]


@pytest.mark.parametrize(
    ("service", "data"),
    [("correct_entry", {"kind": "resident"}), ("add_note", {"note": "hello"})],
)
async def test_no_correctable_entry_gives_a_translated_error(hass: HomeAssistant, setup_guestbook, service, data):
    await ring(hass)  # only a pending ring exists

    with pytest.raises(ServiceValidationError) as error:
        await hass.services.async_call(DOMAIN, service, data, blocking=True)

    assert error.value.translation_domain == DOMAIN
    assert error.value.translation_key == "no_latest_entry"


@pytest.mark.parametrize("language", ["en", "de"])
def test_the_error_is_translated_and_the_optional_id_is_explained(language):
    translations = json.loads((COMPONENT / "translations" / f"{language}.json").read_text())

    assert translations["exceptions"]["no_latest_entry"]["message"]
    for action in ("correct_entry", "add_note"):
        description = translations["services"][action]["fields"]["entry_id"]["description"]
        assert ("latest" in description) or ("letzte" in description)


@pytest.mark.parametrize("action", ["correct_entry", "add_note"])
def test_services_yaml_marks_the_entry_id_as_optional(action):
    fields = yaml.safe_load((COMPONENT / "services.yaml").read_text())[action]["fields"]

    assert not fields["entry_id"].get("required", False)
