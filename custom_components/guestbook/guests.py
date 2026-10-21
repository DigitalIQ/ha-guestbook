"""Guest profiles of a config entry."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry

from .const import CONF_NAME, CONF_TRACKERS, SUBENTRY_GUEST
from .core import Guest


def guests_of(entry: ConfigEntry) -> list[Guest]:
    return [
        Guest(sub.subentry_id, sub.data[CONF_NAME], list(sub.data.get(CONF_TRACKERS, [])))
        for sub in entry.subentries.values()
        if sub.subentry_type == SUBENTRY_GUEST
    ]
