"""Config flow for Guestbook."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    ConfigSubentryFlow,
    SubentryFlowResult,
)
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_LOCKS,
    CONF_NAME,
    CONF_PRESENCE,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
    CONF_TRACKERS,
    DOMAIN,
    SUBENTRY_GUEST,
)


def _entities(*domains: str) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(domain=list(domains) or None, multiple=True))


SOURCES_SCHEMA = probatio.Schema(
    {
        probatio.Optional(CONF_DOORBELLS, default=[]): _entities("event", "binary_sensor"),
        probatio.Optional(CONF_DOORS, default=[]): _entities("binary_sensor"),
        probatio.Optional(CONF_PRESENCE, default=[]): _entities("binary_sensor"),
        probatio.Optional(CONF_LOCKS, default=[]): _entities("lock"),
        probatio.Optional(CONF_RESIDENTS, default=[]): _entities("person"),
        probatio.Optional(CONF_RESIDENT_SIGNALS, default=[]): _entities(),
    }
)


GUEST_SCHEMA = probatio.Schema(
    {
        probatio.Required(CONF_NAME): selector.TextSelector(),
        probatio.Optional(CONF_TRACKERS, default=[]): _entities("device_tracker"),
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


class GuestbookConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    @classmethod
    @callback
    def async_get_supported_subentry_types(cls, config_entry: ConfigEntry) -> dict[str, type[ConfigSubentryFlow]]:
        return {SUBENTRY_GUEST: GuestSubentryFlow}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Guestbook", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SOURCES_SCHEMA)
