"""Reads the registries and states into entity facts and asks the rule core which entities fit a field."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Collection, Mapping
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_DOORBELLS,
    CONF_DOORS,
    CONF_LOCKS,
    CONF_PRESENCE,
    CONF_RESIDENT_SIGNALS,
    CONF_RESIDENTS,
)
from .core.candidates import (
    RESIDENT_SIGNAL_DOMAINS,
    Candidates,
    EntityFacts,
    device_ids_of,
    door_candidates,
    doorbell_candidates,
    guest_tracker_candidates,
    lock_candidates,
    presence_candidates,
    resident_candidates,
    resident_signal_candidates,
)
from .guests import guests_of

FACT_DOMAINS = frozenset({"person", *RESIDENT_SIGNAL_DOMAINS})
MOBILE_APP = "mobile_app"


@callback
def collect_facts(hass: HomeAssistant) -> list[EntityFacts]:
    """One `EntityFacts` per entity with a state. Disabled entities have no state, hidden ones are marked."""
    entities = er.async_get(hass)
    devices = dr.async_get(hass)
    areas = ar.async_get(hass)
    device_domains: dict[str, set[str]] = defaultdict(set)
    for registered in entities.entities.values():
        if registered.device_id:
            device_domains[registered.device_id].add(registered.domain)

    def area_names(area_id: str | None) -> tuple[str, ...]:
        if area_id is None or (area := areas.async_get_area(area_id)) is None:
            return ()
        return (area.name, *area.aliases)

    def area_of(registered: er.RegistryEntry | None) -> tuple[str, ...]:
        """The area of the entity, else of its device, else of the device it hangs off."""
        if registered is None:
            return ()
        if registered.area_id:
            return area_names(registered.area_id)
        device_id, seen = registered.device_id, set()
        while device_id and device_id not in seen and (device := devices.async_get(device_id)) is not None:
            if device.area_id:
                return area_names(device.area_id)
            seen.add(device_id)
            device_id = device.via_device_id
        return ()

    facts = []
    for state in hass.states.async_all(FACT_DOMAINS):
        attributes = state.attributes
        registered = entities.async_get(state.entity_id)
        name = attributes.get("friendly_name") or (registered and (registered.name or registered.original_name)) or ""
        device_class = attributes.get("device_class") or (
            registered and (registered.device_class or registered.original_device_class)
        )
        facts.append(
            EntityFacts(
                entity_id=state.entity_id,
                device_class=device_class or None,
                name=str(name),
                areas=area_of(registered),
                device_id=registered.device_id if registered else None,
                device_domains=frozenset(device_domains.get(registered.device_id, ())) if registered else frozenset(),
                platform=registered.platform if registered else "",
                source_type=attributes.get("source_type"),
                event_types=tuple(attributes.get("event_types") or ()),
                supported_features=attributes.get("supported_features") or 0,
                entity_category=registered.entity_category.value if registered and registered.entity_category else None,
                hidden=bool(registered and registered.hidden_by),
                disabled=bool(registered and registered.disabled_by),
                has_user=attributes.get("user_id") is not None,
                device_trackers=tuple(attributes.get("device_trackers") or ()),
            )
        )
    return facts


@callback
def detect_sources(hass: HomeAssistant) -> dict[str, Candidates]:
    """Doorbells first, then the locks and door contacts, which look at the devices of the doorbell and the lock."""
    facts = collect_facts(hass)
    doorbells = doorbell_candidates(facts)
    bell_devices = device_ids_of(facts, doorbells.suggested)
    locks = lock_candidates(facts, bell_devices)
    anchors = bell_devices | device_ids_of(facts, locks.suggested)
    return {
        CONF_DOORBELLS: doorbells,
        CONF_DOORS: door_candidates(facts, anchors),
        CONF_PRESENCE: presence_candidates(facts),
        CONF_LOCKS: locks,
    }


@callback
def detect_residents(
    hass: HomeAssistant, entry: ConfigEntry | None = None, residents: Collection[str] | None = None
) -> dict[str, Candidates]:
    """Residents, and the resident signals that fit the persons.

    The signals are offered for every person (the form asks for both at once) and preselected for `residents`, which
    is the suggestion of the persons themselves when the caller names none.
    """
    facts = collect_facts(hass)
    persons = resident_candidates(facts)
    suggested = persons.suggested if residents is None else tuple(residents)
    guest_trackers = _guest_trackers(entry)
    signals = resident_signal_candidates(
        facts, persons=persons.listed, suggested_persons=suggested, guest_trackers=guest_trackers
    )
    return {CONF_RESIDENTS: persons, CONF_RESIDENT_SIGNALS: signals}


@callback
def detect_guest_trackers(hass: HomeAssistant, entry: ConfigEntry, guest_id: str | None = None) -> Candidates:
    """Phones for a guest: not a person's, not another guest's, not a resident signal, not a Companion app phone.

    `guest_id` is the guest being edited, whose own phones stay on offer.
    """
    excluded = _guest_trackers(entry, guest_id) | {
        e for e in entry.data.get(CONF_RESIDENT_SIGNALS, []) if e.startswith("device_tracker.")
    }
    return guest_tracker_candidates(_tracker_facts(hass), excluded)


def _tracker_facts(hass: HomeAssistant) -> list[EntityFacts]:
    return [f for f in collect_facts(hass) if f.domain in ("device_tracker", "person")]


def _guest_trackers(entry: ConfigEntry | None, except_guest: str | None = None) -> set[str]:
    guests = guests_of(entry) if entry else []
    return {tracker for guest in guests if guest.id != except_guest for tracker in guest.trackers}


@callback
def suggest_phone_devices(hass: HomeAssistant, residents: Collection[str]) -> list[str]:
    """The Companion app devices of the residents: the `mobile_app` trackers of their persons."""
    entities = er.async_get(hass)
    devices: set[str] = set()
    for person in residents:
        if (state := hass.states.get(person)) is None:
            continue
        for tracker in _as_list(state.attributes.get("device_trackers")):
            registered = entities.async_get(tracker)
            if registered and registered.platform == MOBILE_APP and registered.device_id:
                devices.add(registered.device_id)
    return sorted(devices)


def _as_list(value: Any) -> list[str]:
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []


def stored(config: Mapping[str, Any], key: str) -> list[str]:
    value = config.get(key)
    return [str(v) for v in value] if isinstance(value, (list, tuple)) else []
