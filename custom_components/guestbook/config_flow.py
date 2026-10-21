"""Config flow for Guestbook."""

from __future__ import annotations

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
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_ENTRY_GRACE,
    CONF_LOCKS,
    CONF_MAX_DURATION,
    CONF_NAME,
    CONF_NOTIFY_ENTITIES,
    CONF_PHONE_GRACE,
    CONF_PHONES,
    CONF_PRESENCE,
    CONF_PUSH_ARRIVAL,
    CONF_PUSH_CORRECTION,
    CONF_PUSH_END,
    CONF_PUSH_UNANSWERED_RING,
    CONF_QUIET_PERIOD,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENT_WINDOW,
    CONF_RESIDENTS,
    CONF_RETENTION,
    CONF_RING_WINDOW,
    CONF_TRACKERS,
    DOMAIN,
    PUSH_DEFAULTS,
    SUBENTRY_GUEST,
)
from .settings import rule_defaults


def _entities(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains) or None, multiple=True))


GUEST_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): selector.TextSelector(),
        probatio.Optional(CONF_TRACKERS, default=[]): _entities("device_tracker"),
    }
)

SOURCES_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_DOORBELLS, default=[]): _entities("event", "binary_sensor"),
        probatio.Optional(CONF_DOORS, default=[]): _entities("binary_sensor"),
        probatio.Optional(CONF_PRESENCE, default=[]): _entities("binary_sensor"),
        probatio.Optional(CONF_LOCKS, default=[]): _entities("lock"),
    }
)

RESIDENTS_STEP_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_RESIDENTS, default=[]): _entities("person"),
        probatio.Optional(CONF_RESIDENT_SIGNALS, default=[]): _entities(),
    }
)


# The setup form asks for the sources and the residents in one go.
SOURCES_SCHEMA = probatio.Schema({**SOURCES_STEP_SCHEMA.schema, **RESIDENTS_STEP_SCHEMA.schema})


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
    }
)


class GuestSubentryFlow(ConfigSubentryFlow):
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            return self.async_create_entry(title=name, data={**user_input, CONF_NAME: name})
        return self.async_show_form(step_id="user", data_schema=GUEST_SCHEMA)

    async def async_step_reconfigure(self, user_input: dict[str, Any] | None = None) -> SubentryFlowResult:
        subentry = self._get_reconfigure_subentry()
        if user_input is not None:
            name = user_input[CONF_NAME].strip()
            return self.async_update_and_abort(
                self._get_entry(), subentry, title=name, data={**user_input, CONF_NAME: name}
            )
        return self.async_show_form(
            step_id="reconfigure", data_schema=self.add_suggested_values_to_schema(GUEST_SCHEMA, subentry.data)
        )


class GuestbookOptionsFlow(OptionsFlow):
    """A menu of four steps. Each step saves on its own and applies without a reload."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self.async_show_menu(step_id="init", menu_options=["sources", "residents", "rules", "pushes"])

    async def async_step_sources(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._data_step("sources", SOURCES_STEP_SCHEMA, user_input)

    async def async_step_residents(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._data_step("residents", RESIDENTS_STEP_SCHEMA, user_input)

    async def async_step_rules(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._options_step("rules", RULES_SCHEMA, user_input)

    async def async_step_pushes(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        return self._options_step("pushes", PUSH_SCHEMA, user_input)

    def _data_step(self, step_id: str, schema: probatio.Schema, user_input: dict[str, Any] | None) -> ConfigFlowResult:
        """Sources live in the entry data, as the config flow saved them; the options stay as they are."""
        if user_input is not None:
            self.hass.config_entries.async_update_entry(
                self.config_entry, data={**self.config_entry.data, **user_input}
            )
            return self.async_create_entry(data=dict(self.config_entry.options))
        return self.async_show_form(
            step_id=step_id, data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.data)
        )

    def _options_step(
        self, step_id: str, schema: probatio.Schema, user_input: dict[str, Any] | None
    ) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(data={**self.config_entry.options, **user_input})
        return self.async_show_form(
            step_id=step_id, data_schema=self.add_suggested_values_to_schema(schema, self.config_entry.options)
        )


class GuestbookConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> GuestbookOptionsFlow:
        return GuestbookOptionsFlow()

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_GUEST: GuestSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Guestbook", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SOURCES_SCHEMA)
