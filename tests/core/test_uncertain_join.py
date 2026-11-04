"""A ring plus a door opening or presence while an uncertain visit is open joins that visit."""

from custom_components.guestbook.core import (
    Certainty,
    ChangeKind,
    Engine,
    Entry,
    EntryKind,
    Settings,
    SignalKind,
)

from .helpers import at, signal

DOORBELL = "event.doorbell"
DOOR = "binary_sensor.front_door"
PRESENCE = "binary_sensor.hall_presence"


def open_uncertain_visit(engine: Engine, ring: str = "14:00", door: str = "14:01") -> Entry:
    engine.handle(signal(SignalKind.RING, ring, DOORBELL))
    engine.handle(signal(SignalKind.DOOR_OPEN, door, DOOR))
    (visit,) = engine.active_entries()
    return visit


def test_ring_and_door_while_an_uncertain_visit_is_open_join_that_visit():
    engine = Engine(Settings(), guests=[])
    visit = open_uncertain_visit(engine)

    engine.handle(signal(SignalKind.RING, "14:20", DOORBELL))
    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:21", DOOR))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED, ChangeKind.SIGNAL_ADDED]
    assert changes[0].entry.kind is EntryKind.PENDING_RING
    assert changes[1].entry is visit
    assert engine.active_entries() == [visit]
    assert visit.certainty is Certainty.UNCERTAIN
    assert visit.reason.code == "ring_then_door"
    assert [(s.kind, s.time) for s in visit.signals] == [
        (SignalKind.RING, at("14:00")),
        (SignalKind.DOOR_OPEN, at("14:01")),
        (SignalKind.RING, at("14:20")),
        (SignalKind.DOOR_OPEN, at("14:21")),
    ]


def test_the_door_opening_of_a_joining_guest_does_not_end_the_visit():
    engine = Engine(Settings(), guests=[])
    open_uncertain_visit(engine)
    engine.handle(signal(SignalKind.RING, "14:20", DOORBELL))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:21", DOOR))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:22", DOOR))

    assert engine.advance(at("14:40")) == []
    assert engine.next_deadline() == at("18:00")


def test_a_later_door_opening_still_ends_a_visit_that_a_ring_joined():
    engine = Engine(Settings(), guests=[])
    visit = open_uncertain_visit(engine)
    engine.handle(signal(SignalKind.RING, "14:20", DOORBELL))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:21", DOOR))
    engine.handle(signal(SignalKind.DOOR_OPEN, "15:00", DOOR))

    engine.advance(at("15:10"))

    assert visit.end == at("15:00")
    assert visit.end_reason.code == "door_then_quiet"


def test_a_resident_signal_after_a_joining_ring_keeps_the_visit():
    engine = Engine(Settings(), guests=[])
    visit = open_uncertain_visit(engine)
    engine.handle(signal(SignalKind.RING, "14:20", DOORBELL))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:21", DOOR))

    engine.handle(signal(SignalKind.RESIDENT, "14:22", "device_tracker.sam_phone"))

    assert visit.kind is EntryKind.VISIT
    assert engine.active_entries() == [visit]


def test_presence_after_a_ring_joins_the_open_uncertain_visit_too():
    engine = Engine(Settings(), guests=[])
    visit = open_uncertain_visit(engine)
    engine.handle(signal(SignalKind.RING, "14:20", DOORBELL))

    changes = engine.handle(signal(SignalKind.PRESENCE_ON, "14:24", PRESENCE))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED, ChangeKind.SIGNAL_ADDED]
    assert engine.active_entries() == [visit]
    assert visit.start == at("14:00")
    assert engine.next_deadline() == at("18:00")
