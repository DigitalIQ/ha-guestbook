import json
from datetime import timedelta

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


def make_engine() -> Engine:
    return Engine(Settings(), guests=[])


def test_ring_then_door_opening_starts_an_uncertain_visit():
    engine = make_engine()

    engine.handle(signal(SignalKind.RING, "14:00", "event.doorbell"))
    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:01", "binary_sensor.front_door"))

    (visit,) = engine.active_entries()
    assert visit.kind is EntryKind.VISIT
    assert visit.certainty is Certainty.UNCERTAIN
    assert visit.reason.code == "ring_then_door"
    assert visit.start == at("14:00")
    assert visit.end is None
    assert [s.kind for s in visit.signals] == [SignalKind.RING, SignalKind.DOOR_OPEN]
    assert [c.kind for c in changes] == [ChangeKind.CLASSIFIED]
    assert changes[0].entry is visit


def test_ring_then_presence_starts_an_uncertain_visit():
    engine = make_engine()

    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.PRESENCE_ON, "14:03", "binary_sensor.hall_presence"))

    (visit,) = engine.active_entries()
    assert visit.kind is EntryKind.VISIT
    assert visit.reason.code == "ring_then_presence"
    assert visit.start == at("14:00")


def test_door_or_presence_without_a_ring_does_nothing():
    engine = make_engine()

    changes = [
        *engine.handle(signal(SignalKind.DOOR_OPEN, "14:00")),
        *engine.handle(signal(SignalKind.DOOR_CLOSE, "14:01")),
        *engine.handle(signal(SignalKind.PRESENCE_ON, "14:02")),
        *engine.handle(signal(SignalKind.PRESENCE_OFF, "14:03")),
    ]

    assert changes == []
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_door_opening_after_the_ring_window_does_not_start_a_visit():
    engine = make_engine()

    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:05"))

    assert engine.active_entries() == []


def test_door_opening_just_before_the_end_of_the_ring_window_counts():
    engine = make_engine()

    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:04:59"))

    (visit,) = engine.active_entries()
    assert visit.kind is EntryKind.VISIT


def test_ring_alone_is_pending_and_reports_the_ring_window_end_as_deadline():
    engine = make_engine()

    changes = engine.handle(signal(SignalKind.RING, "14:00"))

    (pending,) = engine.active_entries()
    assert pending.kind is EntryKind.PENDING_RING
    assert [c.kind for c in changes] == [ChangeKind.OPENED]
    assert engine.next_deadline() == at("14:05")


def test_deadline_follows_the_settings_ring_window():
    engine = Engine(Settings(ring_window=timedelta(minutes=2)), guests=[])

    engine.handle(signal(SignalKind.RING, "14:00"))

    assert engine.next_deadline() == at("14:02")


def test_pending_ring_is_dropped_when_the_window_expires():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))

    assert engine.advance(at("14:04:59")) == []
    changes = engine.advance(at("14:05"))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED]
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_deadlines_before_a_signal_fire_before_the_signal_is_handled():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.RING, "14:20"))

    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:21"))

    (visit,) = engine.active_entries()
    assert visit.start == at("14:20")
    assert [s.kind for s in visit.signals] == [SignalKind.RING, SignalKind.DOOR_OPEN]
    assert {c.entry.start for c in changes} == {at("14:20")}


def test_two_rings_before_the_door_opening_make_one_visit():
    engine = make_engine()
    first = engine.handle(signal(SignalKind.RING, "14:00"))[0].entry
    second = engine.handle(signal(SignalKind.RING, "14:01"))[0].entry

    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:02"))

    (visit,) = engine.active_entries()
    assert visit is first
    assert visit.start == at("14:00")
    assert [s.kind for s in visit.signals] == [SignalKind.RING, SignalKind.RING, SignalKind.DOOR_OPEN]
    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.CLOSED, second), (ChangeKind.CLASSIFIED, first)]


def test_engine_is_restorable_from_its_entries_after_a_json_round_trip():
    engine = make_engine()
    expired = engine.handle(signal(SignalKind.RING, "14:00"))[0].entry
    visit = engine.handle(signal(SignalKind.RING, "14:30"))[-1].entry
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:31"))
    pending = engine.handle(signal(SignalKind.RING, "14:32"))[0].entry
    stored = [Entry.from_dict(json.loads(json.dumps(e.to_dict()))) for e in (expired, visit, pending)]

    restored = Engine(Settings(), guests=[], entries=stored)

    assert [e.id for e in restored.active_entries()] == [e.id for e in engine.active_entries()]
    assert restored.next_deadline() == engine.next_deadline()


def test_restored_pending_ring_still_turns_into_a_visit():
    engine = make_engine()
    pending = engine.handle(signal(SignalKind.RING, "14:00"))[0].entry
    restored = Engine(Settings(), guests=[], entries=[Entry.from_dict(pending.to_dict())])

    restored.handle(signal(SignalKind.DOOR_OPEN, "14:02"))

    (visit,) = restored.active_entries()
    assert visit.reason.code == "ring_then_door"


def test_closed_entries_are_not_restored_as_active():
    done = Entry(id="x", kind=EntryKind.VISIT, start=at("10:00"), end=at("11:00"))

    assert Engine(Settings(), guests=[], entries=[done]).active_entries() == []


def test_visit_keeps_a_settings_snapshot_from_decision_time():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.set_settings(Settings(ring_window=timedelta(minutes=9)))

    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01"))

    (visit,) = engine.active_entries()
    assert Settings.from_dict(visit.settings) == Settings(ring_window=timedelta(minutes=9))
