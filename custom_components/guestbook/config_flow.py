"""Config flow for Guestbook."""

from __future__ import annotations

from typing import Any

import probatio
from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.helpers import selector

from .const import CONF_DOORBELLS, CONF_DOORS, CONF_LOCKS, CONF_PRESENCE, CONF_RESIDENT_SIGNALS, CONF_RESIDENTS, DOMAIN


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


class GuestbookConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="Guestbook", data=user_input)
        return self.async_show_form(step_id="user", data_schema=SOURCES_SCHEMA)
