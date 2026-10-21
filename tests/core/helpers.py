from datetime import UTC, datetime

from custom_components.guestbook.core import Signal, SignalKind

DAY = datetime(2026, 10, 21, tzinfo=UTC)


def at(clock: str) -> datetime:
    """Return a UTC datetime on the fixed test day, e.g. at("14:02") or at("14:02:30")."""
    parts = [int(part) for part in clock.split(":")]
    return DAY.replace(hour=parts[0], minute=parts[1], second=parts[2] if len(parts) > 2 else 0)


def signal(kind: SignalKind, clock: str, source: str = "test") -> Signal:
    return Signal(kind=kind, time=at(clock), source=source)
