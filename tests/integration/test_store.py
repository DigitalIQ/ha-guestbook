import logging
from datetime import UTC, datetime

from homeassistant.core import HomeAssistant

from custom_components.guestbook.core import Certainty, Entry, EntryKind

from .conftest import get_visits


async def test_corrupt_stored_item_is_skipped_with_a_warning(
    hass: HomeAssistant, setup_guestbook, hass_storage, caplog
):
    good = Entry(
        id="good",
        kind=EntryKind.VISIT,
        start=datetime(2026, 10, 21, 10, 0, tzinfo=UTC),
        end=datetime(2026, 10, 21, 11, 0, tzinfo=UTC),
        certainty=Certainty.CERTAIN,
        guests=[{"id": "", "name": "Alex"}],
    )
    assert await hass.config_entries.async_unload(setup_guestbook.entry_id)
    hass_storage["guestbook.entries"] = {
        "version": 1,
        "minor_version": 1,
        "key": "guestbook.entries",
        "data": {
            "entries": [
                {"id": "no-kind"},
                good.to_dict(),
                {**good.to_dict(), "id": "bad-kind", "kind": "something_else"},
                {**good.to_dict(), "id": "bad-time", "start": "yesterday"},
                "not even a dict",
            ]
        },
    }

    with caplog.at_level(logging.WARNING):
        assert await hass.config_entries.async_setup(setup_guestbook.entry_id)
        await hass.async_block_till_done()

    assert [e["summary"] for e in await get_visits(hass)] == ["Visit: Alex"]
    skipped = [r for r in caplog.records if r.levelno == logging.WARNING and r.name.endswith("guestbook.store")]
    assert len(skipped) == 4
