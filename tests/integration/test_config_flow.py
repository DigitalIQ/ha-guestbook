from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from custom_components.guestbook.const import (
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_PRESENCE,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
    DOMAIN,
)


async def test_user_creates_an_entry_with_the_selected_sources(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_DOORBELLS: ["event.front_doorbell", "binary_sensor.side_bell"],
            CONF_DOORS: ["binary_sensor.front_door"],
            CONF_PRESENCE: ["binary_sensor.hall_presence"],
            CONF_RESIDENTS: ["person.sam"],
            CONF_RESIDENT_SIGNALS: ["sensor.fingerprint_reader"],
        },
    )

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Guestbook"
    assert result["data"] == {
        CONF_DOORBELLS: ["event.front_doorbell", "binary_sensor.side_bell"],
        CONF_DOORS: ["binary_sensor.front_door"],
        CONF_PRESENCE: ["binary_sensor.hall_presence"],
        CONF_RESIDENTS: ["person.sam"],
        CONF_RESIDENT_SIGNALS: ["sensor.fingerprint_reader"],
    }


async def test_every_source_is_optional(hass: HomeAssistant):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_DOORBELLS: [],
        CONF_DOORS: [],
        CONF_PRESENCE: [],
        CONF_RESIDENTS: [],
        CONF_RESIDENT_SIGNALS: [],
    }


async def test_only_one_instance_is_allowed(hass: HomeAssistant, config_entry):
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "single_instance_allowed"
