from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.guestbook.const import CONF_DOORBELLS, CONF_DOORS, CONF_LOCKS, CONF_PRESENCE, CONF_RESIDENTS
from custom_components.guestbook.core import EffectiveKind

from .conftest import (
    ALEX_PHONE,
    DOOR,
    DOORBELL,
    FINGERPRINT,
    LOCK,
    PRESENCE,
    add_guest,
    advance,
    get_rings,
    get_visits,
    open_options_step,
    ring,
    set_options,
    set_tracker,
)

SIDE_BELL = "binary_sensor.side_bell"
ACTIVE = "binary_sensor.guestbook_visit_active"
RULE_DEFAULTS = {
    "ring_window": 5,
    "resident_window": 3,
    "quiet_period": 10,
    "entry_grace": 2,
    "phone_grace": 5,
    "max_duration": 4,
    "retention": 365,
}


def fields(result: dict) -> dict:
    return {str(key): key for key in result["data_schema"].schema}


async def test_options_menu_offers_sources_residents_rules_and_pushes(hass: HomeAssistant, setup_guestbook):
    result = await hass.config_entries.options.async_init(setup_guestbook.entry_id)

    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["sources", "residents", "rules", "pushes"]


async def test_sources_step_has_the_selectors_of_the_config_flow_including_locks(hass: HomeAssistant, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "sources")

    schema = result["data_schema"].schema
    assert set(fields(result)) == {"doorbells", "doors", "presence", "locks"}
    assert schema[fields(result)["locks"]].config["domain"] == ["lock"]
    assert schema[fields(result)["doorbells"]].config["domain"] == ["event", "binary_sensor"]
    assert result["data_schema"]({"locks": [LOCK]})["locks"] == [LOCK]


async def test_residents_step_has_residents_and_resident_signals(hass: HomeAssistant, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "residents")

    schema = result["data_schema"].schema
    assert set(fields(result)) == {"residents", "resident_signals"}
    assert schema[fields(result)["residents"]].config["domain"] == ["person"]


async def test_rules_step_shows_the_defaults_in_minutes_hours_and_days(hass: HomeAssistant, setup_guestbook):
    result = await open_options_step(hass, setup_guestbook, "rules")

    assert set(fields(result)) == set(RULE_DEFAULTS)
    assert result["data_schema"]({}) == RULE_DEFAULTS


async def test_rules_are_stored_in_the_options_next_to_the_pushes(hass: HomeAssistant, setup_guestbook):
    await set_options(hass, setup_guestbook, push_end=False)

    await set_options(hass, setup_guestbook, step="rules", ring_window=2, max_duration=1.5)

    assert setup_guestbook.options["push_end"] is False
    assert setup_guestbook.options["ring_window"] == 2
    assert setup_guestbook.options["max_duration"] == 1.5
    assert setup_guestbook.options["quiet_period"] == 10


async def test_shorter_ring_window_applies_to_the_next_ring(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", ring_window=1)

    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=2))

    assert len(await get_rings(hass)) == 1


async def test_changed_rules_apply_to_a_visit_that_is_already_open(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    runtime = setup_guestbook.runtime_data

    await set_options(hass, setup_guestbook, step="rules", max_duration=1)

    assert setup_guestbook.runtime_data is runtime
    assert hass.states.get(ACTIVE).state == "on"
    await advance(hass, freezer, timedelta(hours=1))
    assert hass.states.get(ACTIVE).state == "off"
    (event,) = await get_visits(hass)
    assert event["end"] == "2026-10-21T15:00:00+00:00"


async def test_phone_grace_from_the_options_ends_a_phone_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_options(hass, setup_guestbook, step="rules", phone_grace=1)
    await set_tracker(hass, ALEX_PHONE, "home")

    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=1))

    assert hass.states.get(ACTIVE).state == "off"


async def test_settings_of_the_options_are_snapshotted_in_new_entries(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", ring_window=1, retention=90)
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=2))

    (entry,) = setup_guestbook.runtime_data.async_entries(EffectiveKind.UNANSWERED_RING)

    assert entry.settings["ring_window"] == 60.0
    assert entry.settings["retention"] == 90 * 86400.0


async def test_rules_are_used_after_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", ring_window=1)

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=2))

    assert len(await get_rings(hass)) == 1


async def test_changing_sources_keeps_entries_and_open_visits_and_listens_to_the_new_ones(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    runtime = setup_guestbook.runtime_data
    (before,) = runtime.async_open_visits()
    hass.states.async_set(SIDE_BELL, "off")

    await set_options(
        hass, setup_guestbook, step="sources", doorbells=[SIDE_BELL], doors=[DOOR], presence=[PRESENCE], locks=[]
    )

    assert setup_guestbook.runtime_data is runtime
    assert runtime.async_open_visits() == [before]
    assert setup_guestbook.data[CONF_DOORBELLS] == [SIDE_BELL]
    assert setup_guestbook.data[CONF_LOCKS] == []
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))
    await ring(hass)
    await advance(hass, freezer, timedelta(minutes=6))
    assert await get_rings(hass) == []
    hass.states.async_set(SIDE_BELL, "on")
    await hass.async_block_till_done()
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert hass.states.get(ACTIVE).state == "on"


async def test_a_removed_source_no_longer_creates_signals(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="sources", doorbells=[], doors=[DOOR], presence=[], locks=[])

    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    assert hass.states.get(ACTIVE).state == "off"
    assert DOORBELL not in setup_guestbook.data[CONF_DOORBELLS]
    assert setup_guestbook.data[CONF_PRESENCE] == []


async def test_changing_residents_applies_without_a_reload(hass: HomeAssistant, setup_guestbook):
    runtime = setup_guestbook.runtime_data

    await set_options(hass, setup_guestbook, step="residents", residents=["person.sam"], resident_signals=[FINGERPRINT])

    assert setup_guestbook.runtime_data is runtime
    assert setup_guestbook.data[CONF_RESIDENTS] == ["person.sam"]
    assert setup_guestbook.data["resident_signals"] == [FINGERPRINT]
    assert setup_guestbook.data[CONF_DOORS] == [DOOR]
