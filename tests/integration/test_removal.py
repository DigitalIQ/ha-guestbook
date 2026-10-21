from homeassistant.core import HomeAssistant

from .conftest import ALEX_PHONE, add_guest


async def test_removing_the_integration_deletes_the_stored_entries(hass: HomeAssistant, setup_guestbook, hass_storage):
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await hass.services.async_call(
        "guestbook",
        "add_visit",
        {"guests": ["Alex"], "start": "2026-10-20T10:00:00+00:00", "end": "2026-10-20T11:00:00+00:00"},
        blocking=True,
    )
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    assert hass_storage["guestbook.entries"]["data"]["entries"]

    assert await hass.config_entries.async_remove(setup_guestbook.entry_id)

    assert "guestbook.entries" not in hass_storage
