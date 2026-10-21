from datetime import timedelta

from homeassistant.core import HomeAssistant

from custom_components.guestbook.const import DOMAIN
from custom_components.guestbook.core import EffectiveKind

from .conftest import ALEX_PHONE, add_guest, advance, set_options, set_tracker

VISITS = (EffectiveKind.VISIT,)


async def add_visit(hass: HomeAssistant, start: str, end: str) -> None:
    await hass.services.async_call(DOMAIN, "add_visit", {"guests": ["Alex"], "start": start, "end": end}, blocking=True)


def stored_days(entry) -> list[str]:
    return sorted(e.start.date().isoformat() for e in entry.runtime_data.async_entries(*VISITS))


async def restart(hass: HomeAssistant, entry) -> None:
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()


async def test_old_closed_entries_are_purged_at_startup(hass: HomeAssistant, setup_guestbook):
    await set_options(hass, setup_guestbook, step="rules", retention=30)
    await add_visit(hass, "2026-08-01T10:00:00+00:00", "2026-08-01T11:00:00+00:00")
    await add_visit(hass, "2026-10-15T10:00:00+00:00", "2026-10-15T11:00:00+00:00")
    assert stored_days(setup_guestbook) == ["2026-08-01", "2026-10-15"]

    await restart(hass, setup_guestbook)

    assert stored_days(setup_guestbook) == ["2026-10-15"]


async def test_retention_defaults_to_a_year(hass: HomeAssistant, setup_guestbook):
    await add_visit(hass, "2025-12-01T10:00:00+00:00", "2025-12-01T11:00:00+00:00")
    await add_visit(hass, "2025-09-01T10:00:00+00:00", "2025-09-01T11:00:00+00:00")

    await restart(hass, setup_guestbook)

    assert stored_days(setup_guestbook) == ["2025-12-01"]


async def test_purge_runs_once_a_day(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", retention=30)
    await add_visit(hass, "2026-09-21T10:00:00+00:00", "2026-09-21T14:00:00+00:00")
    await advance(hass, freezer, timedelta(hours=23))
    assert stored_days(setup_guestbook) == ["2026-09-21"]

    await advance(hass, freezer, timedelta(hours=1))

    assert stored_days(setup_guestbook) == []


async def test_open_visits_are_never_purged(hass: HomeAssistant, setup_guestbook, freezer):
    await set_options(hass, setup_guestbook, step="rules", retention=30)
    await add_guest(hass, setup_guestbook, "Alex", [ALEX_PHONE])
    await set_tracker(hass, ALEX_PHONE, "home")

    await advance(hass, freezer, timedelta(days=90))

    assert hass.states.get("binary_sensor.guestbook_visit_active").state == "on"
    assert stored_days(setup_guestbook) == ["2026-10-21"]
