"""Actions of Guestbook."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import probatio
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.service import async_register_admin_service
from homeassistant.util import dt as dt_util

from .const import (
    ATTR_END,
    ATTR_ENTRY_ID,
    ATTR_GUEST_NAME,
    ATTR_GUESTS,
    ATTR_KIND,
    ATTR_NOTE,
    ATTR_SOURCE,
    ATTR_START,
    DOMAIN,
    SERVICE_ADD_NOTE,
    SERVICE_ADD_VISIT,
    SERVICE_CORRECT_ENTRY,
    SERVICE_EXPORT,
    SERVICE_RESIDENT_UNLOCK,
)
from .core import CorrectionKind, Signal, SignalKind, clean_guest_name, effective_end, effective_guests, effective_start
from .runtime import GuestbookRuntime

RESIDENT_UNLOCK_SCHEMA = probatio.Schema({probatio.Optional(ATTR_SOURCE): cv.string})
CORRECT_ENTRY_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_ENTRY_ID): cv.string,
        probatio.Required(ATTR_KIND): probatio.Coerce(CorrectionKind),
        probatio.Optional(ATTR_GUEST_NAME): cv.string,
        probatio.Optional(ATTR_START): cv.datetime,
        probatio.Optional(ATTR_END): cv.datetime,
        probatio.Optional(ATTR_NOTE): cv.string,
    }
)


def _guest_name(value: Any) -> str:
    """One guest of `add_visit`: a text (numbers become text), not blank, cut to the maximum length."""
    if not (name := clean_guest_name(cv.string(value))):
        raise probatio.Invalid("a guest name must not be empty")
    return name


ADD_VISIT_SCHEMA = probatio.Schema(
    {
        probatio.Optional(ATTR_GUESTS, default=[]): probatio.All(cv.ensure_list, [_guest_name]),
        probatio.Required(ATTR_START): cv.datetime,
        probatio.Required(ATTR_END): cv.datetime,
        probatio.Optional(ATTR_NOTE): cv.string,
    }
)
ADD_NOTE_SCHEMA = probatio.Schema(
    {probatio.Optional(ATTR_ENTRY_ID): cv.string, probatio.Required(ATTR_NOTE): cv.string}
)
EXPORT_SCHEMA = probatio.Schema({probatio.Optional(ATTR_START): cv.datetime, probatio.Optional(ATTR_END): cv.datetime})


def _utc(value: datetime | None) -> datetime | None:
    return dt_util.as_utc(value) if value is not None else None


@callback
def async_register_services(hass: HomeAssistant) -> None:
    def runtimes() -> list[GuestbookRuntime]:
        if not (entries := hass.config_entries.async_loaded_entries(DOMAIN)):
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="not_loaded")
        return [entry.runtime_data for entry in entries]

    def first_runtime() -> GuestbookRuntime:
        return runtimes()[0]

    async def resident_unlock(call: ServiceCall) -> None:
        signal = Signal(SignalKind.RESIDENT, dt_util.utcnow(), "action", call.data.get(ATTR_SOURCE))
        for runtime in runtimes():
            runtime.async_handle_signal(signal)

    async def correct_entry(call: ServiceCall) -> dict[str, Any] | None:
        runtime = first_runtime()
        entry = runtime.async_correct_entry(
            call.data.get(ATTR_ENTRY_ID),
            call.data[ATTR_KIND],
            guest_name=call.data.get(ATTR_GUEST_NAME),
            start=_utc(call.data.get(ATTR_START)),
            end=_utc(call.data.get(ATTR_END)),
            note=call.data.get(ATTR_NOTE),
        )
        if not call.return_response:
            return None
        end = effective_end(entry)
        return {
            "entry_id": entry.id,
            "kind": call.data[ATTR_KIND].value,
            "decision": entry.kind.value,
            "guests": effective_guests(entry),
            "start": effective_start(entry).isoformat(),
            "end": end.isoformat() if end else None,
        }

    async def add_visit(call: ServiceCall) -> None:
        runtime = first_runtime()
        runtime.async_add_visit(
            call.data[ATTR_GUESTS],
            _utc(call.data[ATTR_START]),
            _utc(call.data[ATTR_END]),
            call.data.get(ATTR_NOTE),
        )

    async def add_note(call: ServiceCall) -> None:
        runtime = first_runtime()
        runtime.async_add_note(call.data.get(ATTR_ENTRY_ID), call.data[ATTR_NOTE])

    async def export(call: ServiceCall) -> dict[str, Any]:
        runtime = first_runtime()
        path, count = await runtime.async_export(_utc(call.data.get(ATTR_START)), _utc(call.data.get(ATTR_END)))
        return {"path": path, "count": count}

    hass.services.async_register(DOMAIN, SERVICE_RESIDENT_UNLOCK, resident_unlock, schema=RESIDENT_UNLOCK_SCHEMA)
    hass.services.async_register(
        DOMAIN,
        SERVICE_CORRECT_ENTRY,
        correct_entry,
        schema=CORRECT_ENTRY_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_ADD_VISIT, add_visit, schema=ADD_VISIT_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_ADD_NOTE, add_note, schema=ADD_NOTE_SCHEMA)
    async_register_admin_service(
        hass, DOMAIN, SERVICE_EXPORT, export, schema=EXPORT_SCHEMA, supports_response=SupportsResponse.OPTIONAL
    )
