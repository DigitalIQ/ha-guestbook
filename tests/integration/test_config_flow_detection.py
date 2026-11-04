"""The setup and options forms offer fitting entities, preselect the likely ones and can show everything."""

import pytest
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity import EntityCategory
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.guestbook.const import DOMAIN

from .conftest import add_guest, add_phone, open_options_step

BELL = "event.front_door_ding"
CONTACT = "binary_sensor.entry_contact"
PATIO = "binary_sensor.patio_contact"
HALL_PRESENCE = "binary_sensor.hall_presence"
LOCK = "lock.front_lock"
SAM = "person.sam"
SAM_ROUTER = "device_tracker.sam_router"
SAM_APP = "device_tracker.sam_app"
KIM = "person.kim"
GUEST_PHONE = "device_tracker.alex_iphone"
TV = "device_tracker.living_room_tv"


@pytest.fixture
def demo(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(domain="demo_hardware")
    entry.add_to_hass(hass)
    return entry


def add_entity(
    hass: HomeAssistant,
    demo: MockConfigEntry,
    entity_id: str,
    state: str = "off",
    *,
    area: str | None = None,
    device: str | None = None,
    **attributes,
) -> None:
    """Register an entity (with a device in an area, if given) and give it a state."""
    domain, object_id = entity_id.split(".")
    device_id = None
    if device:
        device_id = (
            dr.async_get(hass)
            .async_get_or_create(config_entry_id=demo.entry_id, identifiers={("demo_hardware", device)}, name=device)
            .id
        )
    if area:
        area_id = ar.async_get(hass).async_get_or_create(area).id
        if device_id:
            dr.async_get(hass).async_update_device(device_id, area_id=area_id)
    er.async_get(hass).async_get_or_create(
        domain, "demo_hardware", f"{device}-{object_id}", suggested_object_id=object_id, device_id=device_id
    )
    hass.states.async_set(entity_id, state, attributes)


@pytest.fixture
def home(hass: HomeAssistant, demo: MockConfigEntry) -> None:
    add_entity(hass, demo, BELL, "unknown", device="video_doorbell", device_class="doorbell", event_types=["ring"])
    add_entity(hass, demo, "event.hall_remote", "unknown", device="remote", device_class="button")
    add_entity(hass, demo, CONTACT, device="entry_sensor", area="Hallway", device_class="door")
    add_entity(hass, demo, PATIO, device="patio_sensor", area="Living room", device_class="door")
    add_entity(hass, demo, "binary_sensor.kitchen_window", device="window_sensor", device_class="window")
    add_entity(hass, demo, HALL_PRESENCE, device="hall_radar", area="Hallway", device_class="occupancy")
    add_entity(
        hass, demo, "binary_sensor.hall_radar_motion", device="hall_radar", area="Hallway", device_class="motion"
    )
    add_entity(hass, demo, "binary_sensor.battery_low", device="hall_radar", device_class="battery")
    add_entity(hass, demo, LOCK, "locked", device="front_lock", area="Hallway")
    add_entity(hass, demo, "lock.shed_lock", "locked", device="shed_lock")
    add_entity(hass, demo, SAM, "home", user_id="abc", device_trackers=[SAM_ROUTER, SAM_APP])
    add_entity(hass, demo, KIM, "away", device_trackers=["device_tracker.kim_router"])
    add_entity(hass, demo, SAM_ROUTER, "not_home", source_type="router")
    add_entity(hass, demo, SAM_APP, "not_home", source_type="gps")
    add_entity(hass, demo, "device_tracker.kim_router", "not_home", source_type="router")
    add_entity(hass, demo, GUEST_PHONE, "not_home", source_type="router", friendly_name="Alex iPhone")
    add_entity(hass, demo, TV, "home", source_type="router", friendly_name="Living room TV")
    add_entity(hass, demo, "sensor.fingerprint_reader", "unknown", friendly_name="Fingerprint reader")
    add_entity(hass, demo, "sensor.living_temperature", "21", friendly_name="Living temperature")


def schema_of(result: dict) -> dict[str, tuple]:
    return {str(key): (key, value) for key, value in result["data_schema"].schema.items()}


def listed(result: dict, key: str) -> list[str] | None:
    return schema_of(result)[key][1].config.get("include_entities")


def preselected(result: dict, key: str):
    description = schema_of(result)[key][0].description
    return description["suggested_value"] if description else None


async def start_setup(hass: HomeAssistant) -> dict:
    return await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})


# --- setup, step 1 --------------------------------------------------------------------------------------------


async def test_setup_lists_only_fitting_entities_per_field(hass: HomeAssistant, home):
    result = await start_setup(hass)

    assert listed(result, "doorbells") == [BELL]
    assert listed(result, "doors") == [CONTACT, PATIO]
    assert set(listed(result, "presence")) == {HALL_PRESENCE, "binary_sensor.hall_radar_motion"}
    assert set(listed(result, "locks")) == {LOCK, "lock.shed_lock"}


async def test_setup_preselects_the_likely_entities(hass: HomeAssistant, home):
    result = await start_setup(hass)

    assert preselected(result, "doorbells") == [BELL]
    assert preselected(result, "doors") == [CONTACT]
    assert preselected(result, "presence") == [HALL_PRESENCE]
    assert preselected(result, "locks") == [LOCK]


async def test_hidden_disabled_and_diagnostic_entities_are_not_offered(hass: HomeAssistant, demo, home):
    add_entity(hass, demo, "event.diag_ding", "unknown", device="diag", device_class="doorbell")
    add_entity(hass, demo, "event.hidden_ding", "unknown", device="hidden", device_class="doorbell")
    registry = er.async_get(hass)
    registry.async_update_entity("event.diag_ding", entity_category=EntityCategory.DIAGNOSTIC)
    registry.async_update_entity("event.hidden_ding", hidden_by=er.RegistryEntryHider.USER)

    result = await start_setup(hass)

    assert listed(result, "doorbells") == [BELL]


async def test_the_area_of_the_parent_device_counts(hass: HomeAssistant, demo, home):
    add_entity(hass, demo, "binary_sensor.annex_contact", device="annex_sensor", device_class="door")
    registry = dr.async_get(hass)
    hub = registry.async_get_or_create(
        config_entry_id=demo.entry_id, identifiers={("demo_hardware", "hub")}, name="hub"
    )
    registry.async_update_device(hub.id, area_id=ar.async_get(hass).async_get_or_create("Flur").id)
    child_id = er.async_get(hass).async_get("binary_sensor.annex_contact").device_id
    registry.async_update_device(child_id, via_device_id=hub.id)

    result = await start_setup(hass)

    assert set(preselected(result, "doors")) == {CONTACT, "binary_sensor.annex_contact"}


async def test_a_doorbell_binary_sensor_without_a_class_is_found_by_name(hass: HomeAssistant, demo):
    add_entity(hass, demo, "binary_sensor.reolink_visitor", device="reolink", friendly_name="Doorbell Visitor")
    add_entity(hass, demo, "binary_sensor.reolink_motion", device="reolink", device_class="motion")

    result = await start_setup(hass)

    assert listed(result, "doorbells") == ["binary_sensor.reolink_visitor"]
    assert preselected(result, "doorbells") == ["binary_sensor.reolink_visitor"]


async def test_the_fp300_gives_one_suggestion_for_its_two_entities(hass: HomeAssistant, demo):
    add_entity(hass, demo, "binary_sensor.fp300_occupancy", device="fp300", area="Diele", device_class="occupancy")
    add_entity(hass, demo, "binary_sensor.fp300_pir", device="fp300", device_class="motion")
    add_entity(hass, demo, "binary_sensor.fp300_config", device="fp300", device_class="occupancy")
    er.async_get(hass).async_update_entity("binary_sensor.fp300_config", entity_category=EntityCategory.CONFIG)

    result = await start_setup(hass)

    assert set(listed(result, "presence")) == {"binary_sensor.fp300_occupancy", "binary_sensor.fp300_pir"}
    assert preselected(result, "presence") == ["binary_sensor.fp300_occupancy"]


async def test_a_field_without_candidates_shows_all_entities_of_its_kind_and_says_so(hass: HomeAssistant, demo):
    add_entity(hass, demo, CONTACT, device="entry_sensor", area="Hallway", device_class="door")

    result = await start_setup(hass)

    assert listed(result, "doorbells") is None
    assert schema_of(result)["doorbells"][1].config["domain"] == ["event", "binary_sensor"]
    assert listed(result, "doors") == [CONTACT]
    assert "Doorbells" in result["description_placeholders"]["hint"]
    assert "Door contacts" not in result["description_placeholders"]["hint"]


async def test_the_hint_follows_the_language(hass: HomeAssistant, home):
    hass.config.language = "de"

    result = await start_setup(hass)

    assert "Erweitert" in result["description_placeholders"]["hint"]


# --- show all entities ----------------------------------------------------------------------------------------


async def test_show_all_swaps_in_the_unfiltered_lists_and_keeps_the_values(hass: HomeAssistant, home):
    result = await start_setup(hass)

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"doorbells": [BELL], "doors": [PATIO], "advanced": {"show_all": True}}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    for key in ("doorbells", "doors", "presence", "locks"):
        assert listed(result, key) is None
    assert preselected(result, "doors") == [PATIO]
    (toggle,) = schema_of(result)["advanced"][1].schema.schema
    assert toggle.description["suggested_value"] is True
    assert "All entities" in result["description_placeholders"]["hint"]


async def test_after_show_all_an_unlisted_entity_can_be_saved_and_the_flow_goes_on(hass: HomeAssistant, home):
    result = await start_setup(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"advanced": {"show_all": True}})

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"doors": ["binary_sensor.kitchen_window"], "advanced": {"show_all": True}}
    )

    assert result["step_id"] == "residents"


async def test_without_show_all_an_unlisted_entity_is_refused(hass: HomeAssistant, home):
    result = await start_setup(hass)

    with pytest.raises(Exception, match="doors"):
        await hass.config_entries.flow.async_configure(result["flow_id"], {"doors": ["binary_sensor.kitchen_window"]})


async def test_turning_show_all_off_goes_back_to_the_fitting_lists(hass: HomeAssistant, home):
    result = await start_setup(hass)
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"advanced": {"show_all": True}})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"advanced": {"show_all": False}})

    assert result["step_id"] == "user"
    assert listed(result, "doorbells") == [BELL]


async def test_the_entry_has_no_advanced_key(hass: HomeAssistant, home):
    result = await start_setup(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"doors": [CONTACT], "advanced": {"show_all": False}}
    )

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"advanced": {"show_all": False}})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert "advanced" not in result["data"]
    assert result["data"]["doors"] == [CONTACT]


# --- setup, step 2 --------------------------------------------------------------------------------------------


async def test_the_residents_step_suggests_persons_with_a_user_and_their_wifi_trackers(hass: HomeAssistant, home):
    result = await start_setup(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["step_id"] == "residents"
    assert listed(result, "residents") == [SAM, KIM]
    assert preselected(result, "residents") == [SAM]
    assert SAM_ROUTER in listed(result, "resident_signals")
    assert "device_tracker.kim_router" in listed(result, "resident_signals")
    assert "sensor.fingerprint_reader" in listed(result, "resident_signals")
    assert "sensor.living_temperature" not in listed(result, "resident_signals")
    assert GUEST_PHONE not in listed(result, "resident_signals")
    assert preselected(result, "resident_signals") == [SAM_ROUTER]


async def test_the_residents_step_with_nothing_detected_lists_the_signal_domains(hass: HomeAssistant, demo):
    result = await start_setup(hass)

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert listed(result, "resident_signals") is None
    assert "sensor" in schema_of(result)["resident_signals"][1].config["domain"]
    assert "Resident signals" in result["description_placeholders"]["hint"]


# --- options flow ---------------------------------------------------------------------------------------------


async def test_options_show_the_stored_values_and_keep_them_selectable(hass: HomeAssistant, home, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "sources")

    # The stored doorbell, door, presence and lock of the test fixture are not what the detection likes, or not
    # even entities with a registry entry, but they stay in the lists.
    assert "event.front_doorbell" in listed(result, "doorbells")
    assert BELL in listed(result, "doorbells")
    assert preselected(result, "doorbells") == ["event.front_doorbell"]
    assert result["data_schema"]({"doorbells": ["event.front_doorbell"]})["doorbells"] == ["event.front_doorbell"]


async def test_options_keep_an_odd_resident_signal_selectable_and_saveable(hass: HomeAssistant, home, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "residents")

    assert "event.fingerprint_reader" in listed(result, "resident_signals")
    assert "device_tracker.sam_phone" in listed(result, "resident_signals")
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"residents": [], "resident_signals": ["event.fingerprint_reader", "device_tracker.sam_phone"]},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_options_show_all_round_trip_saves_an_unlisted_entity(hass: HomeAssistant, home, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "sources")
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"advanced": {"show_all": True}})
    assert listed(result, "doors") is None

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"doors": ["binary_sensor.kitchen_window"], "advanced": {"show_all": True}}
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert setup_guestbook.data["doors"] == ["binary_sensor.kitchen_window"]
    assert "advanced" not in setup_guestbook.data


async def test_pushes_preselect_the_companion_app_phone_of_a_resident_until_saved(
    hass: HomeAssistant, home, setup_guestbook
):
    device_id = await add_phone(hass, "Pixel of Sam")
    registry = er.async_get(hass)
    registry.async_get_or_create(
        "device_tracker", "mobile_app", "sam-pixel", suggested_object_id="sam_pixel", device_id=device_id
    )
    hass.states.async_set(SAM, "home", {"device_trackers": ["device_tracker.sam_pixel"]})
    hass.config_entries.async_update_entry(setup_guestbook, data={**setup_guestbook.data, "residents": [SAM]})

    result = await open_options_step(hass, setup_guestbook, "pushes")

    assert preselected(result, "phones") == [device_id]


async def test_pushes_keep_a_saved_empty_phone_list(hass: HomeAssistant, home, setup_guestbook):
    device_id = await add_phone(hass, "Pixel of Sam")
    er.async_get(hass).async_get_or_create(
        "device_tracker", "mobile_app", "sam-pixel", suggested_object_id="sam_app", device_id=device_id
    )
    hass.config_entries.async_update_entry(
        setup_guestbook, data={**setup_guestbook.data, "residents": [SAM]}, options={"phones": []}
    )

    result = await open_options_step(hass, setup_guestbook, "pushes")

    assert preselected(result, "phones") == []


# --- guests ---------------------------------------------------------------------------------------------------


async def test_the_guest_form_offers_phones_but_no_resident_taken_or_companion_app_tracker(
    hass: HomeAssistant, demo, home, setup_guestbook
):
    add_entity(hass, demo, "device_tracker.robin_pixel", "not_home", source_type="router", friendly_name="Robin Pixel")
    await add_guest(hass, setup_guestbook, "Robin", ["device_tracker.robin_pixel"])
    hass.config_entries.async_update_entry(setup_guestbook, data={**setup_guestbook.data, "residents": [SAM]})

    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "user"}
    )

    assert listed(result, "trackers") == [GUEST_PHONE]


async def test_the_guest_form_keeps_the_phones_of_the_guest_selectable(hass: HomeAssistant, home, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [GUEST_PHONE, "device_tracker.old_phone"])

    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "reconfigure", "subentry_id": subentry_id}
    )

    assert set(listed(result, "trackers")) == {GUEST_PHONE, "device_tracker.old_phone"}
    assert preselected(result, "trackers") == [GUEST_PHONE, "device_tracker.old_phone"]


async def test_the_guest_form_has_a_show_all_toggle_that_keeps_the_name(hass: HomeAssistant, home, setup_guestbook):
    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "user"}
    )

    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Alex", "advanced": {"show_all": True}}
    )

    assert result["type"] is FlowResultType.FORM
    assert listed(result, "trackers") is None
    assert preselected(result, "name") == "Alex"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Alex", "trackers": [TV], "advanced": {"show_all": True}}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(result["data"]) == {"name": "Alex", "trackers": [TV]}
