"""Maps the rule numbers in the entry options (minutes, hours, days) to the Settings of the rule core."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from .const import (
    CONF_ENTRY_GRACE,
    CONF_MAX_DURATION,
    CONF_PHONE_GRACE,
    CONF_QUIET_PERIOD,
    CONF_RESIDENT_WINDOW,
    CONF_RETENTION,
    CONF_RING_WINDOW,
)
from .core import Settings

# option key -> (Settings field, unit of the option)
RULE_OPTIONS: dict[str, tuple[str, str]] = {
    CONF_RING_WINDOW: ("ring_window", "minutes"),
    CONF_RESIDENT_WINDOW: ("resident_window", "minutes"),
    CONF_QUIET_PERIOD: ("quiet_period", "minutes"),
    CONF_ENTRY_GRACE: ("entry_grace", "minutes"),
    CONF_PHONE_GRACE: ("phone_grace", "minutes"),
    CONF_MAX_DURATION: ("max_duration", "hours"),
    CONF_RETENTION: ("retention", "days"),
}


def settings_from_options(options: Mapping[str, Any]) -> Settings:
    """Build the Settings; options that are not set keep the defaults of the rule core."""
    return Settings(
        **{
            field: timedelta(**{unit: options[key]})
            for key, (field, unit) in RULE_OPTIONS.items()
            if options.get(key) is not None
        }
    )


def rule_defaults() -> dict[str, float]:
    """The default of every rule option in its own unit, taken from the rule core."""
    defaults = Settings()
    return {key: getattr(defaults, field) / timedelta(**{unit: 1}) for key, (field, unit) in RULE_OPTIONS.items()}
