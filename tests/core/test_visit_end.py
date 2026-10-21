import json
from datetime import timedelta

from custom_components.guestbook.core import (
    ChangeKind,
    Engine,
    Entry,
    EntryKind,
    Settings,
    SignalKind,
)

from .helpers import at, signal


def open_visit(engine: Engine, ring: str = "14:00", door: str = "14:01") -> Entry:
    engine.handle(signal(SignalKind.RING, ring, "event.doorbell"))
    engine.handle(signal(SignalKind.DOOR_OPEN, door, "binary_sensor.front_door"))
    (visit,) = engine.active_entries()
    return visit


def test_visit_ends_at_the_door_opening_followed_by_the_quiet_period():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:30", "binary_sensor.front_door"))

    assert engine.next_deadline() == at("14:40")
    assert engine.advance(at("14:39:59")) == []
    changes = engine.advance(at("14:40"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.CLOSED, visit)]
    assert visit.kind is EntryKind.VISIT
    assert visit.end == at("14:30")
    assert visit.end_reason.code == "door_then_quiet"
    assert visit.reason.code == "ring_then_door"
    assert engine.active_entries() == []


def test_second_door_opening_inside_the_quiet_period_moves_the_end():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:30"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:36"))

    assert engine.next_deadline() == at("14:46")
    engine.advance(at("14:46"))

    assert visit.end == at("14:36")
    assert visit.end_reason.code == "door_then_quiet"


def test_door_opening_exactly_at_the_end_of_the_quiet_period_is_too_late():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:30"))

    engine.handle(signal(SignalKind.DOOR_OPEN, "14:40"))

    assert visit.end == at("14:30")
    assert engine.active_entries() == []


def test_door_openings_in_the_entry_grace_do_not_count():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine, door="14:01")
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:02:59"))

    assert engine.next_deadline() == at("18:00")
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:03"))

    assert engine.next_deadline() == at("14:13")
    assert visit.open


def test_entry_grace_counts_from_the_door_opening_that_started_the_visit():
    engine = Engine(Settings(), guests=[])
    open_visit(engine, ring="14:00", door="14:04")

    engine.handle(signal(SignalKind.DOOR_OPEN, "14:05"))

    assert engine.next_deadline() == at("18:00")


def test_visit_without_a_door_opening_ends_at_the_maximum_duration():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)

    assert engine.next_deadline() == at("18:00")
    assert engine.advance(at("17:59:59")) == []
    changes = engine.advance(at("18:00"))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED]
    assert visit.end == at("18:00")
    assert visit.end_reason.code == "max_duration"


def test_maximum_duration_wins_over_a_quiet_period_that_would_end_later():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.handle(signal(SignalKind.DOOR_OPEN, "17:55"))

    assert engine.next_deadline() == at("18:00")
    engine.advance(at("18:00"))

    assert visit.end == at("18:00")
    assert visit.end_reason.code == "max_duration"


def test_rule_numbers_follow_the_settings():
    settings = Settings(
        quiet_period=timedelta(minutes=3), entry_grace=timedelta(minutes=1), max_duration=timedelta(hours=1)
    )
    engine = Engine(settings, guests=[])
    visit = open_visit(engine)

    assert engine.next_deadline() == at("15:00")
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:10"))
    engine.advance(at("14:13"))

    assert visit.end == at("14:10")


def test_signals_during_an_open_visit_are_appended():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    door_close = signal(SignalKind.DOOR_CLOSE, "14:02", "binary_sensor.front_door")
    presence = signal(SignalKind.PRESENCE_ON, "14:03", "binary_sensor.hall_presence")
    lock = signal(SignalKind.LOCK, "14:04", "lock.front_door")

    changes = [c for s in (door_close, presence, lock) for c in engine.handle(s)]

    assert [(c.kind, c.signal, c.entry) for c in changes] == [
        (ChangeKind.SIGNAL_ADDED, s, visit) for s in (door_close, presence, lock)
    ]
    assert visit.signals[-3:] == [door_close, presence, lock]


def test_signals_after_the_visit_ended_are_not_appended():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine, door="14:01")
    engine.advance(at("18:00"))

    changes = engine.handle(signal(SignalKind.PRESENCE_ON, "18:01"))

    assert changes == []
    assert at("18:01") not in [s.time for s in visit.signals]


def test_open_visit_is_restorable_and_ends_correctly():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:30"))
    stored = Entry.from_dict(json.loads(json.dumps(visit.to_dict())))

    restored = Engine(Settings(), guests=[], entries=[stored])

    assert restored.next_deadline() == at("14:40")
    restored.advance(at("15:00"))
    assert stored.end == at("14:30")
    assert stored.end_reason.code == "door_then_quiet"
