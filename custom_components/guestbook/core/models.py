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


class Certainty(StrEnum):
    CERTAIN = "certain"
    UNCERTAIN = "uncertain"


class ChangeKind(StrEnum):
    OPENED = "opened"
    SIGNAL_ADDED = "signal_added"
    CLOSED = "closed"
    CLASSIFIED = "classified"
    CORRECTED = "corrected"


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
    kind: str  # resident | delivery | visit | unknown
    time: datetime
    source: str  # push | action
    guest_name: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
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
            kind=data["kind"],
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
    correction: Correction | None = None
    notes: list[str] = field(default_factory=list)
    settings: dict[str, float] = field(default_factory=dict)  # Settings snapshot at decision time
    rule_state: dict[str, Any] = field(default_factory=dict)  # private engine bookkeeping, JSON-safe

    @property
    def open(self) -> bool:
        return self.end is None

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
            "correction": self.correction.to_dict() if self.correction else None,
            "notes": list(self.notes),
            "settings": dict(self.settings),
            "rule_state": dict(self.rule_state),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Entry:
        return cls(
            id=data["id"],
            kind=EntryKind(data["kind"]),
            start=datetime.fromisoformat(data["start"]),
            end=_dt(data.get("end")),
            certainty=Certainty(data["certainty"]) if data.get("certainty") else None,
            guests=[dict(guest) for guest in data.get("guests", [])],
            signals=[Signal.from_dict(item) for item in data.get("signals", [])],
            reason=Reason.from_dict(data["reason"]) if data.get("reason") else None,
            correction=Correction.from_dict(data["correction"]) if data.get("correction") else None,
            notes=list(data.get("notes", [])),
            settings=dict(data.get("settings", {})),
            rule_state=dict(data.get("rule_state", {})),
        )


@dataclass(frozen=True)
class Change:
    kind: ChangeKind
    entry: Entry
    signal: Signal | None = None
