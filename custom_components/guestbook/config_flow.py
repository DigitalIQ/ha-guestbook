"""Config flow for Guestbook."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_ENTRY_GRACE,
    CONF_MAX_DURATION,
    CONF_NAME,
    CONF_NOTIFY_ENTITIES,
    CONF_PHONE_GRACE,
    CONF_PHONES,
    CONF_PUSH_ARRIVAL,
    CONF_PUSH_CORRECTION,
    CONF_PUSH_END,
    CONF_PUSH_OPEN_PATH,
    CONF_PUSH_UNANSWERED_RING,
    CONF_QUIET_PERIOD,
    CONF_RESIDENT_WINDOW,
    CONF_RESIDENTS,
    CONF_RETENTION,
    CONF_RING_WINDOW,
    CONF_TRACKERS,
    DOMAIN,
    PUSH_DEFAULTS,
    SUBENTRY_GUEST,
)
from .core import clean_guest_name
from .core.candidates import Candidates
from .discovery import (
    detect_guest_trackers,
    detect_residents,
    detect_sources,
    stored,
    suggest_phone_devices,
)
from .forms import (
    DOORBELLS,
    DOORS,
    LOCKS,
    PRESENCE,
    RESIDENT_SIGNALS,
    RESIDENTS,
    TRACKERS,
    Field,
    ShowAllMixin,
)
from .settings import rule_defaults


def _entities(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains) or None, multiple=True))


SOURCE_FIELDS = (DOORBELLS, DOORS, PRESENCE, LOCKS)
RESIDENT_FIELDS = (RESIDENTS, RESIDENT_SIGNALS)
SOURCES_DEFAULTS: dict[str, list[str]] = {field.key: [] for field in (*SOURCE_FIELDS, *RESIDENT_FIELDS)}
GUEST_NAME = {probatio.Required(CONF_NAME): selector.TextSelector()}


def _number(unit: str, minimum: float, maximum: float, step: float) -> selector.NumberSelector:
    return selector.NumberSelector(
        selector.NumberSelectorConfig(
            min=minimum, max=maximum, step=step, unit_of_measurement=unit, mode=selector.NumberSelectorMode.BOX
        )
    )


_RULE_DEFAULTS = rule_defaults()
RULES_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_RING_WINDOW, default=_RULE_DEFAULTS[CONF_RING_WINDOW]): _number("min", 1, 60, 1),
        probatio.Optional(CONF_RESIDENT_WINDOW, default=_RULE_DEFAULTS[CONF_RESIDENT_WINDOW]): _number("min", 1, 60, 1),
        probatio.Optional(CONF_QUIET_PERIOD, default=_RULE_DEFAULTS[CONF_QUIET_PERIOD]): _number("min", 1, 240, 1),
        probatio.Optional(CONF_ENTRY_GRACE, default=_RULE_DEFAULTS[CONF_ENTRY_GRACE]): _number("min", 0, 60, 1),
        probatio.Optional(CONF_PHONE_GRACE, default=_RULE_DEFAULTS[CONF_PHONE_GRACE]): _number("min", 1, 240, 1),
        probatio.Optional(CONF_MAX_DURATION, default=_RULE_DEFAULTS[CONF_MAX_DURATION]): _number("h", 0.5, 72, 0.5),
        probatio.Optional(CONF_RETENTION, default=_RULE_DEFAULTS[CONF_RETENTION]): _number("d", 1, 3650, 1),
    }
)

PUSH_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_PHONES, default=[]): selector.DeviceSelector(
            selector.DeviceSelectorConfig(integration="mobile_app", multiple=True)
        ),
        probatio.Optional(CONF_NOTIFY_ENTITIES, default=[]): _entities("notify"),
        probatio.Optional(CONF_PUSH_ARRIVAL, default=PUSH_DEFAULTS[CONF_PUSH_ARRIVAL]): selector.BooleanSelector(),
        probatio.Optional(CONF_PUSH_END, default=PUSH_DEFAULTS[CONF_PUSH_END]): selector.BooleanSelector(),
        probatio.Optional(
            CONF_PUSH_CORRECTION, default=PUSH_DEFAULTS[CONF_PUSH_CORRECTION]
        ): selector.BooleanSelector(),
        probatio.Optional(
            CONF_PUSH_UNANSWERED_RING, default=PUSH_DEFAULTS[CONF_PUSH_UNANSWERED_RING]
        ): selector.BooleanSelector(),
        probatio.Optional(CONF_PUSH_OPEN_PATH, default=""): selector.TextSelector(),
    }
)


class GuestSubentryFlow(ShowAllMixin, ConfigSubentryFlow):
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        return self._guest_step("user", user_input, {}, None)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        return self._guest_step("reconfigure", user_input, dict(subentry.data), subentry.subentry_id)

    def _guest_step(
        self, step_id: str, user_input: dict[str, Any] | None, current: dict[str, Any], guest_id: str | None
    ) -> SubentryFlowResult:
        suggested = current
        if user_input is not None:
            data, switched = self._split_input(user_input)
            if not switched:
                name = clean_guest_name(data[CONF_NAME])
                data = {**data, CONF_NAME: name}
                if step_id == "user":
                    return self.async_create_entry(title=name, data=data)
                return self.async_update_and_abort(
                    self._get_entry(), self._get_reconfigure_subentry(), title=name, data=data
                )
            suggested = data
        detected = {CONF_TRACKERS: detect_guest_trackers(self.hass, self._get_entry(), guest_id)}
        return self._detecting_form(step_id, (TRACKERS,), detected, current, suggested, head=GUEST_NAME)


class GuestbookOptionsFlow(ShowAllMixin, OptionsFlow):
    """A menu of four steps. Each step saves on its own and applies without a reload."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["sources", "residents", "rules", "pushes"])

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._data_step("sources", SOURCE_FIELDS, user_input, detect_sources(self.hass))

    async def async_step_residents(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._data_step(
            "residents",
            RESIDENT_FIELDS,
            user_input,
            detect_residents(self.hass, self.config_entry, stored(self.config_entry.data, CONF_RESIDENTS)),
        )

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._options_step("rules", RULES_SCHEMA, user_input)

    async def async_step_pushes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        suggested = self.config_entry.options
        if CONF_PHONES not in suggested:
            residents = stored(self.config_entry.data, CONF_RESIDENTS)
            suggested = {**suggested, CONF_PHONES: suggest_phone_devices(self.hass, residents)}
        return self._options_step("pushes", PUSH_SCHEMA, user_input, suggested)

    def _data_step(
        self,
        step_id: str,
        fields: tuple[Field, ...],
        user_input: dict[str, Any] | None,
        detected: dict[str, Candidates],
    ) -> ConfigFlowResult:
        """Sources live in the entry data, as the config flow saved them; the options stay as they are."""
        suggested = self.config_entry.data
        if user_input is not None:
            data, switched = self._split_input(user_input)
            if not switched:
                self.hass.config_entries.async_update_entry(self.config_entry, data={**self.config_entry.data, **data})
                return self.async_create_entry(data=dict(self.config_entry.options))
            suggested = {**suggested, **data}
        return self._detecting_form(step_id, fields, detected, self.config_entry.data, suggested)

    def _options_step(
        self,
        step_id: str,
        schema: probatio.Schema,
        user_input: dict[str, Any] | None,
        suggested: Mapping[str, Any] | None = None,
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        return self.async_show_form(
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(
                schema, self.config_entry.options if suggested is None else suggested
            ),
        )


class GuestbookConfigFlow(ShowAllMixin, ConfigFlow, domain=DOMAIN):
    """Setup in two steps: the sources, then the residents and their signals (which depend on the persons)."""

    VERSION = 1

    def __init__(self) -> None:
        self._sources: dict[str, Any] = {}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GuestbookOptionsFlow:
        return GuestbookOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_GUEST: GuestSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        detected = detect_sources(self.hass)
        suggested = {key: list(found.suggested) for key, found in detected.items()}
        if user_input is not None:
            data, switched = self._split_input(user_input)
            if not switched:
                self._saved()
                self._sources = data
                return await self.async_step_residents()
            suggested = data
        return self._detecting_form("user", SOURCE_FIELDS, detected, {}, suggested)

    async def async_step_residents(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        detected = detect_residents(self.hass)
        suggested = {key: list(found.suggested) for key, found in detected.items()}
        if user_input is not None:
            data, switched = self._split_input(user_input)
            if not switched:
                return self.async_create_entry(title="Guestbook", data={**SOURCES_DEFAULTS, **self._sources, **data})
            suggested = data
        return self._detecting_form("residents", RESIDENT_FIELDS, detected, {}, suggested)
