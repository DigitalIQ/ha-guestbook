"""Sends pushes to the selected phones and notify entities."""

from __future__ import annotations

import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import STATE_HOME
from homeassistant.core import CALLBACK_TYPE, Event, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import device_registry as dr
from homeassistant.util import slugify

from .const import (
    CONF_NOTIFY_ENTITIES,
    CONF_PHONES,
    CONF_PUSH_ARRIVAL,
    CONF_PUSH_CORRECTION,
    CONF_PUSH_END,
    CONF_PUSH_UNANSWERED_RING,
    CONF_RESIDENTS,
    PUSH_DEFAULTS,
    SOURCE_PUSH,
)
from .core import (
    Certainty,
    Change,
    ChangeKind,
    Entry,
    EntryKind,
    PushKind,
    correction_actions,
    parse_action_id,
    push_message,
    push_title,
)
from .runtime import GuestbookRuntime

_LOGGER = logging.getLogger(__name__)

MOBILE_APP = "mobile_app"
EVENT_NOTIFICATION_ACTION = "mobile_app_notification_action"
SWITCHES = {
    PushKind.ARRIVAL: CONF_PUSH_ARRIVAL,
    PushKind.END: CONF_PUSH_END,
    PushKind.CORRECTION: CONF_PUSH_CORRECTION,
    PushKind.UNANSWERED_RING: CONF_PUSH_UNANSWERED_RING,
}
WHEN_NO_RESIDENT_HOME = (PushKind.ARRIVAL, PushKind.END)
SKIPPED_END_REASONS = {"corrected"}


class Notifier:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, runtime: GuestbookRuntime) -> None:
        self._hass = hass
        self._entry = entry
        self._runtime = runtime

    @callback
    def async_start(self) -> CALLBACK_TYPE:
        unsubs = [
            self._runtime.async_add_change_listener(self._handle_change),
            self._hass.bus.async_listen(EVENT_NOTIFICATION_ACTION, self._handle_action),
        ]

        @callback
        def stop() -> None:
            for unsub in unsubs:
                unsub()

        return stop

    @callback
    def _handle_action(self, event: Event) -> None:
        """Save the answer to a correction question; anything that is not ours or not valid is ignored."""
        if (parsed := parse_action_id(str(event.data.get("action", "")))) is None:
            return
        kind, entry_id = parsed
        guest_name = (str(event.data.get("reply_text") or "").strip() or None) if kind == "visit" else None
        try:
            self._runtime.async_correct_entry(entry_id, kind, guest_name=guest_name, source=SOURCE_PUSH)
        except ServiceValidationError as err:
            _LOGGER.debug("Ignoring the answer for entry %s: %s", entry_id, err)

    @callback
    def _handle_change(self, change: Change) -> None:
        entry = change.entry
        if entry.kind is EntryKind.VISIT and change.previous is None:
            if change.kind in (ChangeKind.OPENED, ChangeKind.CLASSIFIED) and entry.open:
                self._push(PushKind.ARRIVAL, entry)
                if entry.certainty is Certainty.UNCERTAIN:
                    self._push(PushKind.CORRECTION, entry)
            elif change.kind is ChangeKind.CLOSED and entry.end is not None:
                if entry.end_reason is None or entry.end_reason.code not in SKIPPED_END_REASONS:
                    self._push(PushKind.END, entry)
        elif entry.kind is EntryKind.UNANSWERED_RING and change.kind is ChangeKind.CLASSIFIED:
            self._push(PushKind.UNANSWERED_RING, entry)

    @callback
    def _push(self, kind: PushKind, entry: Entry) -> None:
        options = self._entry.options
        if not options.get(SWITCHES[kind], PUSH_DEFAULTS[SWITCHES[kind]]):
            return
        if kind in WHEN_NO_RESIDENT_HOME and self._resident_home():
            return
        language = self._hass.config.language
        guests = [guest["name"] for guest in entry.guests]
        title = push_title(kind, language)
        for device_id in options.get(CONF_PHONES, []):
            if (phone := self._phone(device_id)) is None:
                continue
            service, android = phone
            payload: dict[str, Any] = {"title": title, "message": push_message(kind, language, guests)}
            if kind is PushKind.CORRECTION:
                actions = correction_actions(language, entry.id, android=android)
                payload["data"] = {"tag": entry.id, "actions": actions}
            self._call(service, payload)
        if entities := options.get(CONF_NOTIFY_ENTITIES, []):
            message = push_message(kind, language, guests, entry_id=entry.id)
            self._call("send_message", {"entity_id": list(entities), "title": title, "message": message})

    def _resident_home(self) -> bool:
        return any(
            self._hass.states.is_state(person, STATE_HOME) for person in self._entry.data.get(CONF_RESIDENTS, [])
        )

    def _phone(self, device_id: str) -> tuple[str, bool] | None:
        """Return the legacy notify service of a Companion app device and whether it runs Android."""
        device = dr.async_get(self._hass).async_get(device_id)
        mobile_app = next(
            (
                config_entry
                for entry_id in (device.config_entries if device else ())
                if (config_entry := self._hass.config_entries.async_get_entry(entry_id))
                and config_entry.domain == MOBILE_APP
            ),
            None,
        )
        if device is None or mobile_app is None:
            _LOGGER.debug("Skipping device %s: it is not a Companion app phone", device_id)
            return None
        service = f"{MOBILE_APP}_{slugify(mobile_app.data.get('device_name') or device.name or '')}"
        if not self._hass.services.has_service("notify", service):
            _LOGGER.debug("Skipping %s: the service notify.%s does not exist", device.name, service)
            return None
        return service, str(mobile_app.data.get("os_name", "")).casefold() == "android"

    @callback
    def _call(self, service: str, data: dict[str, Any]) -> None:
        self._hass.async_create_task(self._async_call(service, data))

    async def _async_call(self, service: str, data: dict[str, Any]) -> None:
        try:
            await self._hass.services.async_call("notify", service, data, blocking=True)
        except HomeAssistantError as err:
            _LOGGER.warning("Could not send the push through notify.%s: %s", service, err)
