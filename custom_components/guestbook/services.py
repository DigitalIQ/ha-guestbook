"""Actions of Guestbook."""

from __future__ import annotations

import probatio
from homeassistant.core import HomeAssistant, ServiceCall, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.util import dt as dt_util

from .const import ATTR_SOURCE, DOMAIN, SERVICE_RESIDENT_UNLOCK
from .core import Signal, SignalKind

RESIDENT_UNLOCK_SCHEMA = probatio.Schema({probatio.Optional(ATTR_SOURCE): cv.string})


@callback
def async_register_services(hass: HomeAssistant) -> None:
    async def resident_unlock(call: ServiceCall) -> None:
        if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        signal = Signal(SignalKind.RESIDENT, dt_util.utcnow(), "action", call.data.get(ATTR_SOURCE))
        for entry in entries:
            entry.runtime_data.async_handle_signal(signal)

    hass.services.async_register(DOMAIN, SERVICE_RESIDENT_UNLOCK, resident_unlock, schema=RESIDENT_UNLOCK_SCHEMA)
