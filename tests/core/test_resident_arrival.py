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

RESIDENT = SignalKind.RESIDENT


def make_engine(**settings) -> Engine:
    return Engine(Settings(**settings), guests=[])


def test_resident_signal_before_the_ring_makes_the_ring_a_resident_arrival():
    engine = make_engine()
    unlock = signal(RESIDENT, "14:00", "sensor.fingerprint")
    ring = signal(SignalKind.RING, "14:01", "event.doorbell")
    engine.handle(unlock)

    changes = engine.handle(ring)

    (change,) = changes
    arrival = change.entry
    assert change.kind is ChangeKind.CLASSIFIED
    assert arrival.kind is EntryKind.RESIDENT_ARRIVAL
    assert arrival.reason.code == "resident_signal"
    assert arrival.signals == [unlock, ring]
    assert (arrival.start, arrival.end) == (at("14:01"), at("14:01"))
    assert arrival.certainty is None
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_door_opening_after_a_resident_arrival_starts_nothing():
    engine = make_engine()
    engine.handle(signal(RESIDENT, "14:00"))
    engine.handle(signal(SignalKind.RING, "14:01"))

    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:02"))

    assert changes == []
    assert engine.active_entries() == []


def test_resident_window_is_inclusive_at_its_start():
    engine = make_engine()
    engine.handle(signal(RESIDENT, "14:00"))

    (change,) = engine.handle(signal(SignalKind.RING, "14:03"))

    assert change.entry.kind is EntryKind.RESIDENT_ARRIVAL


def test_resident_signal_older_than_the_resident_window_does_not_count():
    engine = make_engine()
    engine.handle(signal(RESIDENT, "14:00"))

    (change,) = engine.handle(signal(SignalKind.RING, "14:03:01"))

    assert change.kind is ChangeKind.OPENED
    assert change.entry.kind is EntryKind.PENDING_RING


def test_resident_window_follows_the_settings():
    engine = make_engine(resident_window=timedelta(minutes=10))
    engine.handle(signal(RESIDENT, "14:00"))

    (change,) = engine.handle(signal(SignalKind.RING, "14:09"))

    assert change.entry.kind is EntryKind.RESIDENT_ARRIVAL


def test_resident_signal_while_a_ring_is_pending_makes_it_a_resident_arrival():
    engine = make_engine()
    ring = signal(SignalKind.RING, "14:00")
    unlock = signal(RESIDENT, "14:02", "action")
    pending = engine.handle(ring)[0].entry

    changes = engine.handle(unlock)

    (change,) = changes
    assert change.kind is ChangeKind.CLASSIFIED
    assert change.entry is pending
    assert pending.kind is EntryKind.RESIDENT_ARRIVAL
    assert pending.reason.code == "resident_signal"
    assert pending.signals == [ring, unlock]
    assert (pending.start, pending.end) == (at("14:00"), at("14:02"))
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_resident_signal_wins_over_a_later_door_opening():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(RESIDENT, "14:01"))

    assert engine.handle(signal(SignalKind.DOOR_OPEN, "14:02")) == []
    assert engine.active_entries() == []


def test_resident_signal_after_the_ring_window_is_too_late():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))

    changes = engine.handle(signal(RESIDENT, "14:05"))

    assert [c for c in changes if c.entry.kind is EntryKind.RESIDENT_ARRIVAL] == []


def test_resident_signal_reclassifies_a_visit_started_inside_the_ring_window():
    engine = make_engine()
    visit = None
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01"))
    (visit,) = engine.active_entries()
    unlock = signal(RESIDENT, "14:02", "sensor.fingerprint")

    changes = engine.handle(unlock)

    (change,) = changes
    assert change.kind is ChangeKind.CLASSIFIED
    assert change.entry is visit
    assert visit.kind is EntryKind.RESIDENT_ARRIVAL
    assert visit.reason.code == "resident_signal"
    assert visit.certainty is None
    assert visit.end_reason is None
    assert visit.end == at("14:02")
    assert [s.kind for s in visit.signals] == [SignalKind.RING, SignalKind.DOOR_OPEN, RESIDENT]
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_resident_signal_after_the_ring_window_leaves_a_visit_alone():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01"))
    (visit,) = engine.active_entries()

    changes = engine.handle(signal(RESIDENT, "14:05"))

    assert changes == []
    assert visit.kind is EntryKind.VISIT
    assert visit.open


def test_resident_signal_with_nothing_to_decide_changes_nothing():
    engine = make_engine()

    assert engine.handle(signal(RESIDENT, "14:00")) == []
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_every_pending_ring_in_the_window_becomes_a_resident_arrival():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.RING, "14:01"))

    changes = engine.handle(signal(RESIDENT, "14:02"))

    assert [c.entry.kind for c in changes] == [EntryKind.RESIDENT_ARRIVAL] * 2
    assert engine.active_entries() == []


def test_resident_arrival_keeps_a_settings_snapshot():
    engine = make_engine()
    engine.handle(signal(RESIDENT, "14:00"))
    engine.set_settings(Settings(ring_window=timedelta(minutes=9)))

    (change,) = engine.handle(signal(SignalKind.RING, "14:01"))

    assert Settings.from_dict(change.entry.settings) == Settings(ring_window=timedelta(minutes=9))


def test_restored_pending_ring_still_becomes_a_resident_arrival():
    pending = make_engine().handle(signal(SignalKind.RING, "14:00"))[0].entry
    restored = Engine(Settings(), guests=[], entries=[Entry.from_dict(json.loads(json.dumps(pending.to_dict())))])

    (change,) = restored.handle(signal(RESIDENT, "14:01"))

    assert change.entry.kind is EntryKind.RESIDENT_ARRIVAL


def test_resident_signals_are_not_restored_after_a_restart():
    engine = make_engine()
    engine.handle(signal(RESIDENT, "14:00"))
    restarted = Engine(Settings(), guests=[])

    (change,) = restarted.handle(signal(SignalKind.RING, "14:01"))

    assert change.entry.kind is EntryKind.PENDING_RING


def test_change_of_a_reclassified_visit_remembers_the_visit_it_was():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01"))

    (change,) = engine.handle(signal(RESIDENT, "14:02"))

    assert change.previous.kind is EntryKind.VISIT
    assert change.previous.certainty is Certainty.UNCERTAIN


def test_change_of_a_reclassified_pending_ring_remembers_the_pending_ring():
    engine = make_engine()
    engine.handle(signal(SignalKind.RING, "14:00"))

    (change,) = engine.handle(signal(RESIDENT, "14:01"))

    assert change.previous.kind is EntryKind.PENDING_RING
