"""Ranks the entities of a home for the fields of the setup forms. No Home Assistant imports.

The integration reads the registries and states into `EntityFacts`. The functions here decide which entities fit a
field (`listed`) and which of them are the likely pick (`suggested`). Evidence in order of strength: device class,
name words (English and German), the area and the device it shares with other sources.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable, Collection, Iterable
from dataclasses import dataclass

NO_CANDIDATES: tuple[str, ...] = ()

_UMLAUTS = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})


def fold(text: str) -> str:
    """Lower case, with German umlauts spelled out and other accents removed ("Haustür" becomes "haustuer")."""
    text = text.lower().translate(_UMLAUTS)
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


# Name words. Patterns run on folded text, where `_` and `-` count as separators for the \b boundaries below.
BELL_WORDS = re.compile(
    r"doorbell|door bell|klingel|\bbell\b|\bbells\b|visitor|besucher|deurbel|sonnette|campanello|gong|chime|\bding\b"
    r"|\bring\b|\bringing\b"
)
DOOR_WORDS = re.compile(r"(?<!out)(?<!in)door|haustue?r|tuer|\btue?r\b|eingang|entrance|\bfront\b|gate|\btor\b|pforte")
FRONT_WORDS = re.compile(r"haustue?r|front|eingang|entrance|\bmain\b|\bhaupt")
SIGNAL_WORDS = re.compile(
    r"finger|ekey|keypad|\bnfc\b|rfid|\bcode\b|unlock|entsperr|\bpin\b|\btag\b|badge|transponder|\bkey\b|schluessel"
)
RESIDENT_WORDS = re.compile(r"resident|bewohner|\bhome\b|zuhause|arriv|ankunft|anwesen|\bwelcome\b")
PHONE_WORDS = re.compile(r"iphone|ipad|android|galaxy|pixel|phone|handy|xiaomi|oneplus|huawei|watch|smartphone|\bmi \d")
INFRASTRUCTURE_WORDS = re.compile(
    r"\btv\b|fernseher|drucker|printer|\bnas\b|repeater|switch|\bcam\b|camera|kamera|fire ?stick|\becho\b|alexa|sonos"
    r"|\besp|shelly|tasmota|router|accesspoint|access point|\bap\b|chromecast|playstation|xbox|\bpc\b|laptop|desktop"
    r"|raspberry|homeassistant|\bhue\b|bridge|soundbar|speaker|lautsprecher|receiver"
)
ENTRANCE_AREA_WORDS = re.compile(
    r"\bhallway\b|\bhall\b|entrance|\bentry\b|entryway|foyer|porch|vestibule|corridor|\bgang\b|diele|windfang"
    r"|flur|eingang|haustue?r|treppenhaus|vorraum|vorzimmer|front door|garderobe"
)
OUTDOOR_WORDS = re.compile(
    r"garden|garten|terrace|terrasse|driveway|einfahrt|carport|street|strasse|\byard\b|outdoor|outside|aussen|balcon"
    r"|balkon"
)

RING_EVENT_TYPES = frozenset({"ring", "rang", "doorbell", "doorbell_ring", "ding", "visitor", "klingel"})
PRESS_EVENT_TYPES = frozenset({"press", "pressed", "single", "single_press", "short_press", "initial_press", "button"})

# `LockEntityFeature.OPEN`, the lock opens the latch ("front door"), not just the bolt.
LOCK_FEATURE_OPEN = 1

# The domains whose entities can produce a resident signal (see the signal adapter).
RESIDENT_SIGNAL_DOMAINS = ("event", "device_tracker", "binary_sensor", "lock", "input_boolean", "switch", "sensor")


@dataclass(frozen=True, slots=True)
class EntityFacts:
    """What the registries and the state machine know about one entity."""

    entity_id: str
    device_class: str | None = None
    name: str = ""
    areas: tuple[str, ...] = ()  # names and aliases of the area of the entity, else of its device
    device_id: str | None = None
    device_domains: frozenset[str] = frozenset()  # domains of all entities on the same device
    platform: str = ""  # the integration that created the entity
    source_type: str | None = None  # device_tracker: router, bluetooth, bluetooth_le, gps
    event_types: tuple[str, ...] = ()
    supported_features: int = 0
    entity_category: str | None = None  # config or diagnostic
    hidden: bool = False
    disabled: bool = False
    has_user: bool = False  # person: linked to a Home Assistant user
    device_trackers: tuple[str, ...] = ()  # person: the tracked devices

    @property
    def domain(self) -> str:
        return self.entity_id.split(".", 1)[0]

    @property
    def text(self) -> str:
        """The folded name and entity id, the text the name words run on."""
        return fold(f"{self.name} {self.entity_id.split('.', 1)[1]}".replace("_", " "))


@dataclass(frozen=True, slots=True)
class Candidates:
    """The entities that fit a field, best first, and the ones to preselect."""

    listed: tuple[str, ...] = NO_CANDIDATES
    suggested: tuple[str, ...] = NO_CANDIDATES

    def __bool__(self) -> bool:
        return bool(self.listed)


@dataclass(frozen=True, slots=True)
class _Hit:
    facts: EntityFacts
    score: int


def usable(facts: EntityFacts) -> bool:
    """A hidden, disabled, config or diagnostic entity is never offered."""
    return not (facts.hidden or facts.disabled or facts.entity_category)


def in_entrance_area(facts: EntityFacts) -> bool:
    return any(ENTRANCE_AREA_WORDS.search(fold(area)) for area in facts.areas)


def _outdoor(facts: EntityFacts) -> bool:
    return any(OUTDOOR_WORDS.search(fold(area)) for area in facts.areas) or bool(OUTDOOR_WORDS.search(facts.text))


def _pack(hits: Iterable[_Hit], suggest: Callable[[list[_Hit]], Iterable[_Hit]]) -> Candidates:
    ranked = sorted((hit for hit in hits if hit.score > 0), key=lambda hit: (-hit.score, hit.facts.entity_id))
    return Candidates(
        listed=tuple(hit.facts.entity_id for hit in ranked),
        suggested=tuple(hit.facts.entity_id for hit in suggest(ranked)),
    )


def doorbell_candidates(facts: Iterable[EntityFacts]) -> Candidates:
    """`event` and `binary_sensor` entities that look like a doorbell."""
    hits = [_Hit(f, _doorbell_score(f)) for f in facts if usable(f) and f.domain in ("event", "binary_sensor")]

    def suggest(ranked: list[_Hit]) -> list[_Hit]:
        if not ranked or ranked[0].score < 70:
            return []
        return [hit for hit in ranked if hit.score == ranked[0].score]

    return _pack(hits, suggest)


def _doorbell_score(f: EntityFacts) -> int:
    bell = bool(BELL_WORDS.search(f.text))
    if f.domain == "event":
        if f.device_class == "doorbell":
            return 100
        if bell:
            return 70
        types = set(f.event_types)
        if types & RING_EVENT_TYPES:
            return 60
        if types & PRESS_EVENT_TYPES:
            if "camera" in f.device_domains:
                return 50
            if in_entrance_area(f):
                return 30
        return 0
    # A binary sensor: doorbells often have no device class. A bell word next to a motion class is the motion
    # sensor of a doorbell camera, listed but not suggested.
    if not bell:
        return 0
    return 40 if f.device_class in ("motion", "occupancy", "presence", "moving") else 70


def lock_candidates(facts: Iterable[EntityFacts], doorbell_devices: Collection[str] = ()) -> Candidates:
    """Every lock, the ones at the entrance first."""
    hits = [_Hit(f, _lock_score(f, doorbell_devices)) for f in facts if usable(f) and f.domain == "lock"]

    def suggest(ranked: list[_Hit]) -> list[_Hit]:
        if len(ranked) == 1:
            return ranked
        return [hit for hit in ranked if hit.score >= 40]

    return _pack(hits, suggest)


def _lock_score(f: EntityFacts, doorbell_devices: Collection[str]) -> int:
    score = 10
    if in_entrance_area(f):
        score += 30
    if f.device_id and f.device_id in doorbell_devices:
        score += 30
    if f.supported_features & LOCK_FEATURE_OPEN:
        score += 10
    return score


def door_candidates(facts: Iterable[EntityFacts], anchor_devices: Collection[str] = ()) -> Candidates:
    """Door contacts. `anchor_devices` are the devices of the suggested locks and doorbells."""
    hits = [_Hit(f, _door_score(f, anchor_devices)) for f in facts if usable(f) and f.domain == "binary_sensor"]

    def suggest(ranked: list[_Hit]) -> list[_Hit]:
        return [hit for hit in ranked if hit.score >= 100]

    return _pack(hits, suggest)


def _door_score(f: EntityFacts, anchor_devices: Collection[str]) -> int:
    door_words = bool(DOOR_WORDS.search(f.text)) and not BELL_WORDS.search(f.text)
    match f.device_class:
        case "door":
            score = 80
        case "opening":
            score = 60
        case "garage_door":
            score = 20
        case "window":
            score = 30 if door_words else 0
        case None:
            score = 40 if door_words else 0
        case _:
            score = 0
    if score == 0:
        return 0
    if FRONT_WORDS.search(f.text) and score >= 60:
        score += 20
    if in_entrance_area(f):
        score += 30
    if f.device_id and f.device_id in anchor_devices:
        score += 30
    return score


def presence_candidates(facts: Iterable[EntityFacts]) -> Candidates:
    """Occupancy, presence and motion sensors. Only an entrance area makes one a suggestion."""
    hits = [_Hit(f, _presence_score(f)) for f in facts if usable(f) and f.domain == "binary_sensor"]

    def suggest(ranked: list[_Hit]) -> list[_Hit]:
        # One per device: a sensor with an occupancy and a motion entity, or several zones, gives its best entity.
        best: dict[str, _Hit] = {}
        picks: list[_Hit] = []
        for hit in ranked:
            if _outdoor(hit.facts) or not in_entrance_area(hit.facts):
                continue
            device = hit.facts.device_id
            if device is None:
                picks.append(hit)
            elif device not in best or _zone_order(hit) < _zone_order(best[device]):
                best[device] = hit
        return [*picks, *best.values()]

    return _pack(hits, suggest)


def _zone_order(hit: _Hit) -> tuple[int, int, str]:
    return (-hit.score, len(hit.facts.text), hit.facts.entity_id)


def _presence_score(f: EntityFacts) -> int:
    match f.device_class:
        case "occupancy" | "presence":
            score = 70
        case "motion":
            score = 50
        case _:
            return 0
    # An entrance in the garden is a place people walk past, not the way into the home.
    if _outdoor(f):
        return score - 30
    return score + 40 if in_entrance_area(f) else score


def resident_candidates(facts: Iterable[EntityFacts]) -> Candidates:
    """All persons. The ones linked to a Home Assistant user are the likely residents."""
    hits = [_Hit(f, 50 if f.has_user else 10) for f in facts if usable(f) and f.domain == "person"]
    return _pack(hits, lambda ranked: [hit for hit in ranked if hit.facts.has_user])


def resident_signal_candidates(
    facts: Iterable[EntityFacts],
    persons: Collection[str],
    suggested_persons: Collection[str] = (),
    guest_trackers: Collection[str] = (),
) -> Candidates:
    """Entities that can prove a resident is arriving.

    `persons` are the person entities whose trackers are offered, `suggested_persons` the ones whose trackers are
    preselected (the residents). `guest_trackers` are never offered.
    """
    facts = list(facts)
    by_id = {f.entity_id: f for f in facts}
    offered = {t for p in persons if p in by_id for t in by_id[p].device_trackers}
    wanted = {t for p in suggested_persons if p in by_id for t in by_id[p].device_trackers}
    hits = [
        _Hit(f, _signal_score(f, f.entity_id in offered))
        for f in facts
        if usable(f) and f.domain in RESIDENT_SIGNAL_DOMAINS and f.entity_id not in guest_trackers
    ]

    def suggest(ranked: list[_Hit]) -> list[_Hit]:
        return [hit for hit in ranked if hit.facts.entity_id in wanted and hit.score >= 90]

    return _pack(hits, suggest)


_SIGNAL_BASE = {"event": 70, "binary_sensor": 60, "sensor": 50, "input_boolean": 40, "switch": 40}


def _signal_score(f: EntityFacts, own_tracker: bool) -> int:
    if f.domain == "device_tracker":
        if not own_tracker:
            return 0
        # Joining the Wi-Fi or being heard by a Bluetooth scanner is the early proof of an arrival.
        return 40 if f.source_type == "gps" else 90
    if f.domain == "lock":
        return 20
    if SIGNAL_WORDS.search(f.text):
        return _SIGNAL_BASE[f.domain]
    if RESIDENT_WORDS.search(f.text) and f.domain in ("event", "binary_sensor", "input_boolean", "switch"):
        return 20
    return 0


def guest_tracker_candidates(facts: Iterable[EntityFacts], excluded: Collection[str] = ()) -> Candidates:
    """Phones that can identify a guest: no resident's or other guest's tracker, no Companion app phone."""
    facts = list(facts)
    taken = set(excluded)
    for f in facts:
        taken.update(f.device_trackers)
    hits = [
        _Hit(f, _tracker_score(f))
        for f in facts
        if usable(f) and f.domain == "device_tracker" and f.entity_id not in taken and f.platform != "mobile_app"
    ]
    return _pack(hits, lambda ranked: [])


def _tracker_score(f: EntityFacts) -> int:
    match f.source_type:
        case "router" | "bluetooth_le":
            score = 60
        case "bluetooth":
            score = 40
        case "gps":
            score = 10
        case _:
            score = 20
    if PHONE_WORDS.search(f.text):
        score += 30
    if INFRASTRUCTURE_WORDS.search(f.text):
        score -= 70
    return score


def device_ids_of(facts: Iterable[EntityFacts], entity_ids: Collection[str]) -> frozenset[str]:
    """The devices that hold the given entities, to find a door contact or a lock next to a doorbell."""
    return frozenset(f.device_id for f in facts if f.entity_id in entity_ids and f.device_id)
