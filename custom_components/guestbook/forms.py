"""Entity selectors that offer only the fitting entities, with a "Show all entities" escape hatch.

A form lists the detected candidates of each field as `include_entities`. Values the field already holds are always
added, so a stored setup never fails validation. A collapsed section "Advanced" has one toggle. Submitting it flips
the form to the unfiltered selectors (or back) without saving; the next submit without a flip saves.
"""

from __future__ import annotations

from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Any

import probatio
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import section
from homeassistant.helpers import selector

from .core.candidates import RESIDENT_SIGNAL_DOMAINS, Candidates
from .discovery import stored

ADVANCED = "advanced"
SHOW_ALL = "show_all"


@dataclass(frozen=True)
class Field:
    """An optional list of entities. `domains` are the domains it holds (none: any domain).

    `fallback_domains` narrow the unfiltered list when nothing was detected, as long as the stored values fit them.
    """

    key: str
    domains: tuple[str, ...] = ()
    fallback_domains: tuple[str, ...] = ()


DOORBELLS = Field("doorbells", ("event", "binary_sensor"))
DOORS = Field("doors", ("binary_sensor",))
PRESENCE = Field("presence", ("binary_sensor",))
LOCKS = Field("locks", ("lock",))
RESIDENTS = Field("residents", ("person",))
RESIDENT_SIGNALS = Field("resident_signals", fallback_domains=RESIDENT_SIGNAL_DOMAINS)
TRACKERS = Field("trackers", ("device_tracker",))

_LABELS = {
    "en": {
        "doorbells": "Doorbells",
        "doors": "Door contacts",
        "presence": "Presence sensors",
        "locks": "Locks",
        "residents": "Residents",
        "resident_signals": "Resident signals",
        "trackers": "Phones",
    },
    "de": {
        "doorbells": "Türklingeln",
        "doors": "Türkontakte",
        "presence": "Anwesenheitssensoren",
        "locks": "Schlösser",
        "residents": "Bewohner",
        "resident_signals": "Bewohnersignale",
        "trackers": "Handys",
    },
}
_HINTS = {
    "en": {
        "filtered": (
            "Only fitting entities are listed. If yours is missing, open Advanced, turn on Show all entities and "
            "submit."
        ),
        "empty": "Nothing fitting was found for {fields}, so those fields list all entities of their kind.",
        "all": (
            "All entities are listed. To see only the fitting ones again, turn off Show all entities under Advanced "
            "and submit."
        ),
    },
    "de": {
        "filtered": (
            "Es werden nur passende Entitäten angezeigt. Fehlt deine, öffne Erweitert, schalte Alle Entitäten "
            "anzeigen ein und sende ab."
        ),
        "empty": "Für {fields} wurde nichts Passendes gefunden, deshalb zeigen diese Felder alle Entitäten ihrer Art.",
        "all": (
            "Alle Entitäten werden angezeigt. Für nur die passenden schaltest du unter Erweitert Alle Entitäten "
            "anzeigen aus und sendest ab."
        ),
    },
}


def _language(hass: HomeAssistant) -> str:
    return "de" if hass.config.language.lower().startswith("de") else "en"


def hint(hass: HomeAssistant, show_all: bool, empty: Collection[str]) -> str:
    """The sentence under the step description: which list is shown and what to do if an entity is missing."""
    language = _language(hass)
    texts, labels = _HINTS[language], _LABELS[language]
    if show_all:
        return texts["all"]
    text = texts["filtered"]
    if empty:
        text += " " + texts["empty"].format(fields=", ".join(labels[key] for key in empty))
    return text


def _advanced() -> section:
    return section(
        probatio.Schema({probatio.Optional(SHOW_ALL, default=False): selector.BooleanSelector()}),
        {"collapsed": True},
    )


def _entities(config: dict[str, Any]) -> selector.EntitySelector:
    return selector.EntitySelector(selector.EntitySelectorConfig(multiple=True, **config))


def _selector(field: Field, candidates: Candidates | None, keep: list[str]) -> selector.EntitySelector:
    """The selector of one field: the candidates and the values to keep, or all entities of the field's kind."""
    if candidates:
        ids = list(dict.fromkeys([*candidates.listed, *keep]))
        return _entities({"include_entities": ids, **({"domain": list(field.domains)} if field.domains else {})})
    domains = field.domains
    if (
        candidates is not None
        and field.fallback_domains
        and all(e.split(".", 1)[0] in field.fallback_domains for e in keep)
    ):
        domains = field.fallback_domains
    return _entities({"domain": list(domains)} if domains else {})


def detecting_schema(
    fields: Collection[Field],
    detected: Mapping[str, Candidates],
    keep: Mapping[str, Any],
    show_all: bool,
    head: Mapping[Any, Any] | None = None,
) -> tuple[probatio.Schema, list[str]]:
    """The schema of a step and the keys of the fields for which nothing was detected.

    `head` holds the fields in front of the entity lists (a name). `keep` are the values that must stay selectable.
    """
    schema: dict[Any, Any] = dict(head or {})
    empty: list[str] = []
    for field in fields:
        candidates = None if show_all else detected.get(field.key, Candidates())
        if candidates is not None and not candidates:
            empty.append(field.key)
        schema[probatio.Optional(field.key, default=[])] = _selector(field, candidates, stored(keep, field.key))
    schema[probatio.Optional(ADVANCED)] = _advanced()
    return probatio.Schema(schema), empty


class ShowAllMixin:
    """The state and the rendering of a form with the "Show all entities" toggle.

    The mode lives on the flow, not in the entry. It starts filtered and resets when a step is saved.
    """

    hass: HomeAssistant
    _show_all = False

    def _split_input(self, user_input: Mapping[str, Any]) -> tuple[dict[str, Any], bool]:
        """The data without the Advanced section, and whether the toggle asks for the other list."""
        data = dict(user_input)
        advanced = data.pop(ADVANCED, None) or {}
        wanted = bool(advanced.get(SHOW_ALL, self._show_all))
        switched = wanted != self._show_all
        self._show_all = wanted
        return data, switched

    def _saved(self) -> None:
        self._show_all = False

    def _detecting_form(
        self,
        step_id: str,
        fields: Collection[Field],
        detected: Mapping[str, Candidates],
        keep: Mapping[str, Any],
        suggested: Mapping[str, Any] | None = None,
        head: Mapping[Any, Any] | None = None,
        placeholders: Mapping[str, str] | None = None,
    ) -> Any:
        """Show a step. `suggested` are the prefilled values; they stay selectable as well."""
        keep = {**keep, **{k: v for k, v in (suggested or {}).items() if isinstance(v, list)}}
        schema, empty = detecting_schema(fields, detected, keep, self._show_all, head)
        values = {**(suggested or {}), ADVANCED: {SHOW_ALL: self._show_all}}
        return self.async_show_form(  # type: ignore[attr-defined]
            step_id=step_id,
            data_schema=self.add_suggested_values_to_schema(schema, values),  # type: ignore[attr-defined]
            description_placeholders={**(placeholders or {}), "hint": hint(self.hass, self._show_all, empty)},
        )
