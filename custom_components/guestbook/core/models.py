"""Data model of the rule core. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


MAX_GUEST_NAME = 64  # characters; guest names end up in entity states, titles and pushes


def _aware(value: Any) -> bool:
    """True for an ISO string with a UTC offset."""
    try:
        return isinstance(value, str) and datetime.fromisoformat(value).tzinfo is not None
    except ValueError:
        return False


def normalize_name(name: str) -> str:
    """The form in which guest names are compared: trimmed and case-insensitive."""
    return name.strip().casefold()


def clean_guest_name(name: str) -> str:
    """A guest name as it is stored: trimmed and cut to `MAX_GUEST_NAME` characters."""
    return name.strip()[:MAX_GUEST_NAME].rstrip()


class SignalKind(StrEnum):
    RING = "ring"
    DOOR_OPEN = "door_open"
    DOOR_CLOSE = "door_close"
    PRESENCE_ON = "presence_on"
    PRESENCE_OFF = "presence_off"
    LOCK = "lock"
    GUEST_HOME = "guest_home"
    GUEST_AWAY = "guest_away"
    RESIDENT = "resident"


class EntryKind(StrEnum):
    PENDING_RING = "pending_ring"
    VISIT = "visit"
    UNANSWERED_RING = "unanswered_ring"
    RESIDENT_ARRIVAL = "resident_arrival"


class CorrectionKind(StrEnum):
    RESIDENT = "resident"
    DELIVERY = "delivery"
    VISIT = "visit"
    UNKNOWN = "unknown"


class Certainty(StrEnum):
    CERTAIN = "certain"
    UNCERTAIN = "uncertain"


class ChangeKind(StrEnum):
    OPENED = "opened"
    SIGNAL_ADDED = "signal_added"
    CLOSED = "closed"
    CLASSIFIED = "classified"
    CORRECTED = "corrected"
    GUEST_LEFT = "guest_left"


LEFT_GUESTS = "left_guests"  # key in Entry.rule_state: ids of guests who left a visit that went on without them


@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    time: datetime
    source: str
    state: str | None = None
    guest_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "time": self.time.isoformat(),
            "source": self.source,
            "state": self.state,
            "guest_id": self.guest_id,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Signal:
        return cls(
            kind=SignalKind(data["kind"]),
            time=datetime.fromisoformat(data["time"]),
            source=data["source"],
            state=data.get("state"),
            guest_id=data.get("guest_id"),
        )


@dataclass
class Reason:
    code: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Reason:
        return cls(code=data["code"], detail=data.get("detail", ""))


@dataclass
class Correction:
    kind: CorrectionKind
    time: datetime
    source: str  # push | action | button
    guest_name: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        self.kind = CorrectionKind(self.kind)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "time": self.time.isoformat(),
            "source": self.source,
            "guest_name": self.guest_name,
            "start": _iso(self.start),
            "end": _iso(self.end),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Correction:
        return cls(
            kind=CorrectionKind(data["kind"]),
            time=datetime.fromisoformat(data["time"]),
            source=data["source"],
            guest_name=data.get("guest_name"),
            start=_dt(data.get("start")),
            end=_dt(data.get("end")),
            note=data.get("note"),
        )


@dataclass
class Guest:
    id: str
    name: str
    trackers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "trackers": list(self.trackers)}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Guest:
        return cls(id=data["id"], name=data["name"], trackers=list(data.get("trackers", [])))


@dataclass
class Settings:
    ring_window: timedelta = timedelta(minutes=5)
    resident_window: timedelta = timedelta(minutes=3)
    quiet_period: timedelta = timedelta(minutes=10)
    entry_grace: timedelta = timedelta(minutes=2)  # door openings this soon after start do not end a visit
    phone_grace: timedelta = timedelta(minutes=5)
    max_duration: timedelta = timedelta(hours=4)
    retention: timedelta = timedelta(days=365)

    def to_dict(self) -> dict[str, float]:
        return {f.name: getattr(self, f.name).total_seconds() for f in fields(self)}

    @classmethod
    def from_dict(cls, data: dict[str, float]) -> Settings:
        known = {f.name for f in fields(cls)}
        return cls(**{key: timedelta(seconds=value) for key, value in data.items() if key in known})


@dataclass
class Entry:
    id: str
    kind: EntryKind
    start: datetime
    end: datetime | None = None
    certainty: Certainty | None = None
    guests: list[dict[str, str]] = field(default_factory=list)  # [{"id": ..., "name": ...}]
    signals: list[Signal] = field(default_factory=list)
    reason: Reason | None = None
    end_reason: Reason | None = None
    correction: Correction | None = None
    notes: list[str] = field(default_factory=list)
    settings: dict[str, float] = field(default_factory=dict)  # Settings snapshot at decision time
    rule_state: dict[str, Any] = field(default_factory=dict)  # private engine bookkeeping, JSON-safe
    question_token: str | None = None  # one-time token of the pending correction question, never exported
    dropped_signals: int = 0  # ordinary signals that were dropped because the entry hit the signal cap

    @property
    def open(self) -> bool:
        return self.end is None

    @property
    def present_guest_ids(self) -> set[str]:
        """Ids of the guests of the entry who are still there: not left (all phones away for the phone grace)."""
        left = self.rule_state.get(LEFT_GUESTS, ())
        return {guest["id"] for guest in self.guests if guest["id"] and guest["id"] not in left}

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind.value,
            "start": self.start.isoformat(),
            "end": _iso(self.end),
            "certainty": self.certainty.value if self.certainty else None,
            "guests": [dict(guest) for guest in self.guests],
            "signals": [signal.to_dict() for signal in self.signals],
            "reason": self.reason.to_dict() if self.reason else None,
            "end_reason": self.end_reason.to_dict() if self.end_reason else None,
            "correction": self.correction.to_dict() if self.correction else None,
            "notes": list(self.notes),
            "settings": dict(self.settings),
            "rule_state": dict(self.rule_state),
            "question_token": self.question_token,
            "dropped_signals": self.dropped_signals,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        """Read a stored entry; raises KeyError, TypeError or ValueError for one the engine could not work with."""
        entry = cls._from_dict(data)
        entry._check()
        return entry

    def _check(self) -> None:
        """Invariants the rule core relies on: guests with id and name, a timezone-aware deadline on a pending ring."""
        for guest in self.guests:
            if not (
                isinstance(guest, dict) and isinstance(guest.get("id"), str) and isinstance(guest.get("name"), str)
            ):
                raise ValueError(f"entry {self.id}: a guest needs a text id and a text name")
        if self.kind is EntryKind.PENDING_RING and self.open and not _aware(self.rule_state.get("deadline")):
            raise ValueError(f"entry {self.id}: a pending ring needs a timezone-aware deadline")

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Entry:
        return cls(
            id=data["id"],
            kind=EntryKind(data["kind"]),
            start=datetime.fromisoformat(data["start"]),
            end=_dt(data.get("end")),
            certainty=Certainty(data["certainty"]) if data.get("certainty") else None,
            guests=[dict(guest) for guest in data.get("guests", [])],
            signals=[Signal.from_dict(item) for item in data.get("signals", [])],
            reason=Reason.from_dict(data["reason"]) if data.get("reason") else None,
            end_reason=Reason.from_dict(data["end_reason"]) if data.get("end_reason") else None,
            correction=Correction.from_dict(data["correction"]) if data.get("correction") else None,
            notes=list(data.get("notes", [])),
            settings=dict(data.get("settings", {})),
            rule_state=dict(data.get("rule_state", {})),
            question_token=data.get("question_token"),
            dropped_signals=int(data.get("dropped_signals", 0)),
        )


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    entry: Entry
    signal: Signal | None = None
    previous: Entry | None = None  # shallow copy of the entry before a reclassification
