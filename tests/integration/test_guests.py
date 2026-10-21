from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.guestbook.const import DOMAIN

from .conftest import (
    ALEX_PHONE,
    ALEX_TABLET,
    DOOR,
    SAM_PHONE,
    add_guest,
    advance,
    get_visits,
    ring,
    set_tracker,
)


async def test_guest_subentry_stores_name_and_trackers(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE, ALEX_TABLET])

    subentry = setup_guestbook.subentries[subentry_id]
    assert subentry.subentry_type == "guest"
    assert subentry.title == "Alex"
    assert dict(subentry.data) == {"name": "Alex", "trackers": [ALEX_PHONE, ALEX_TABLET]}


async def test_guest_form_offers_name_and_device_trackers(hass: HomeAssistant, setup_guestbook):
    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "user"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    assert set(result["data_schema"].schema) == {"name", "trackers"}


async def test_reconfigure_updates_the_guest(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "reconfigure", "subentry_id": subentry_id}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reconfigure"
    result = await hass.config_entries.subentries.async_configure(
        result["flow_id"], {"name": "Alexandra", "trackers": [ALEX_TABLET]}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    subentry = setup_guestbook.subentries[subentry_id]
    assert subentry.title == "Alexandra"
    assert dict(subentry.data) == {"name": "Alexandra", "trackers": [ALEX_TABLET]}


async def test_guest_phone_joining_starts_a_visit_named_after_the_guest(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert hass.states.get("calendar.guestbook_visits").state == "on"
    assert hass.states.get("calendar.guestbook_visits").attributes["message"] == "Visit: Alex"


async def test_phone_visit_ends_when_the_phone_left_for_the_grace_period(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(hours=1))

    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=4))
    assert hass.states.get("calendar.guestbook_visits").state == "on"
    await advance(hass, freezer, timedelta(minutes=1))

    assert hass.states.get("calendar.guestbook_visits").state == "off"
    (event,) = await get_visits(hass)
    assert event["start"] == "2026-10-21T14:00:00+00:00"
    assert event["end"] == "2026-10-21T15:00:00+00:00"


async def test_phone_dropping_out_of_the_network_does_not_split_the_visit(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=30))

    await set_tracker(hass, ALEX_PHONE, "unavailable")
    await advance(hass, freezer, timedelta(minutes=30))
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(hours=1))

    assert hass.states.get("calendar.guestbook_visits").state == "on"
    assert len(await get_visits(hass)) == 1


async def test_phone_leaving_through_unavailable_still_ends_the_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=30))

    await set_tracker(hass, ALEX_PHONE, "unavailable")
    await advance(hass, freezer, timedelta(minutes=30))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))

    assert hass.states.get("calendar.guestbook_visits").state == "off"
    (event,) = await get_visits(hass)
    assert event["end"] == "2026-10-21T15:00:00+00:00"


async def test_phone_arriving_through_unavailable_starts_a_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "unavailable")

    await set_tracker(hass, ALEX_PHONE, "home")

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert hass.states.get("calendar.guestbook_visits").state == "on"


async def test_phone_not_home_before_and_after_unavailable_starts_nothing(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    await set_tracker(hass, ALEX_PHONE, "unavailable")
    await set_tracker(hass, ALEX_PHONE, "not_home")

    assert await get_visits(hass) == []


async def test_phone_back_within_the_grace_period_keeps_one_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=30))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=3))
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(hours=1))

    assert hass.states.get("calendar.guestbook_visits").state == "on"
    assert len(await get_visits(hass)) == 1


async def test_two_guests_share_one_visit(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await add_guest(hass, setup_guestbook, "Sam", [SAM_PHONE])

    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=10))
    await set_tracker(hass, SAM_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=10))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=10))
    assert hass.states.get("calendar.guestbook_visits").state == "on"
    await set_tracker(hass, SAM_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex, Sam"
    assert event["end"] == "2026-10-21T14:30:00+00:00"


async def test_guest_phone_makes_an_uncertain_visit_certain(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()
    assert [e["summary"] for e in await get_visits(hass)] == ["Visit (uncertain)"]

    await advance(hass, freezer, timedelta(minutes=2))
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(hours=5))

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert event["start"] == "2026-10-21T14:00:00+00:00"
    assert hass.states.get("calendar.guestbook_visits").state == "on"


async def test_new_guest_works_without_a_restart_and_keeps_open_visits(hass: HomeAssistant, setup_guestbook, freezer):
    await ring(hass)
    hass.states.async_set(DOOR, "on")
    await hass.async_block_till_done()

    await add_guest(hass, setup_guestbook, "Sam", [SAM_PHONE])

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit (uncertain)"]
    await set_tracker(hass, SAM_PHONE, "home")
    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Sam"]


async def test_reconfigured_phone_is_watched_and_the_old_one_is_not(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    hass.states.async_set(ALEX_TABLET, "not_home")
    result = await hass.config_entries.subentries.async_init(
        (setup_guestbook.entry_id, "guest"), context={"source": "reconfigure", "subentry_id": subentry_id}
    )
    await hass.config_entries.subentries.async_configure(result["flow_id"], {"name": "Alex", "trackers": [ALEX_TABLET]})
    await hass.async_block_till_done()

    await set_tracker(hass, ALEX_PHONE, "home")
    assert await get_visits(hass) == []
    await set_tracker(hass, ALEX_TABLET, "home")
    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Alex"]


async def test_removed_guest_no_longer_starts_visits(hass: HomeAssistant, setup_guestbook):
    subentry_id = await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    hass.config_entries.async_remove_subentry(setup_guestbook, subentry_id)
    await hass.async_block_till_done()
    await set_tracker(hass, ALEX_PHONE, "home")

    assert await get_visits(hass) == []


async def test_open_phone_visit_continues_after_a_restart(hass: HomeAssistant, setup_guestbook, freezer):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=30))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert event["end"] == "2026-10-21T14:30:00+00:00"
    assert DOMAIN in hass.config.components


async def test_guest_phone_already_home_when_the_guest_is_added_starts_a_certain_visit(
    hass: HomeAssistant, setup_guestbook
):
    hass.states.async_set(ALEX_PHONE, "home")

    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert event["start"] == "2026-10-21T14:00:00+00:00"
    assert hass.states.get("binary_sensor.alex_visiting").state == "on"


async def test_guest_phone_already_home_at_startup_starts_a_certain_visit(
    hass: HomeAssistant, setup_guestbook, freezer, hass_storage
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass_storage["guestbook.entries"]["data"]["entries"].clear()
    await advance(hass, freezer, timedelta(minutes=10))
    hass.states.async_set(ALEX_PHONE, "home")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    (event,) = await get_visits(hass)
    assert event["summary"] == "Visit: Alex"
    assert event["start"] == "2026-10-21T14:10:00+00:00"
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    (stored,) = hass_storage["guestbook.entries"]["data"]["entries"]
    assert stored["reason"]["code"] == "guest_phone_at_start"


async def test_restored_visit_with_the_guest_is_not_duplicated_at_startup(hass: HomeAssistant, setup_guestbook):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    assert await hass.config_entries.async_reload(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    (event,) = await get_visits(hass)
    assert event["start"] == "2026-10-21T14:00:00+00:00"


async def test_restored_visit_ends_when_the_phone_left_during_the_downtime(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(ALEX_PHONE, "not_home")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.alex_visiting").state == "on"
    await advance(hass, freezer, timedelta(minutes=5))

    (event,) = await get_visits(hass)
    assert event["end"] == "2026-10-21T14:30:00+00:00"
    assert hass.states.get("binary_sensor.alex_visiting").state == "off"


async def test_restored_visit_stays_open_when_the_phone_is_unavailable_at_startup(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(ALEX_PHONE, "unavailable")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    assert hass.states.get("binary_sensor.alex_visiting").state == "on"


async def test_restored_visit_ends_when_the_phone_that_was_unavailable_at_startup_is_not_home(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(ALEX_PHONE, "unavailable")
    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()

    await set_tracker(hass, ALEX_PHONE, "not_home")
    await advance(hass, freezer, timedelta(minutes=5))

    assert hass.states.get("binary_sensor.alex_visiting").state == "off"
    (event,) = await get_visits(hass)
    assert event["end"] == "2026-10-21T14:30:00+00:00"


async def test_restored_visit_stays_open_while_one_of_two_phones_is_still_home(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE, ALEX_TABLET])
    await set_tracker(hass, ALEX_PHONE, "home")
    await set_tracker(hass, ALEX_TABLET, "home")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await advance(hass, freezer, timedelta(minutes=30))
    hass.states.async_set(ALEX_TABLET, "not_home")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    assert hass.states.get("binary_sensor.alex_visiting").state == "on"


async def test_restored_visit_continues_when_the_phone_returned_during_the_downtime(
    hass: HomeAssistant, setup_guestbook, freezer
):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")
    await advance(hass, freezer, timedelta(minutes=10))
    await set_tracker(hass, ALEX_PHONE, "not_home")
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    await advance(hass, freezer, timedelta(minutes=2))
    hass.states.async_set(ALEX_PHONE, "home")

    assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
    await hass.async_block_till_done()
    await advance(hass, freezer, timedelta(minutes=10))

    (event,) = await get_visits(hass)
    assert event["start"] == "2026-10-21T14:00:00+00:00"
    assert hass.states.get("binary_sensor.alex_visiting").state == "on"
