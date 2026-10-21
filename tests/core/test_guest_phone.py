from datetime import timedelta

from custom_components.guestbook.core import (
    Certainty,
    ChangeKind,
    Engine,
    Entry,
    EntryKind,
    Guest,
    Settings,
    Signal,
    SignalKind,
)

from .helpers import at, signal

ALEX = Guest("alex", "Alex", ["device_tracker.alex_phone", "device_tracker.alex_tablet"])
SAM = Guest("sam", "Sam", ["device_tracker.sam_phone"])
ALEX_PHONE = "device_tracker.alex_phone"
ALEX_TABLET = "device_tracker.alex_tablet"
SAM_PHONE = "device_tracker.sam_phone"


def phone(kind: SignalKind, clock: str, guest_id: str, tracker: str) -> Signal:
    return Signal(kind, at(clock), tracker, guest_id=guest_id)


def home(clock: str, guest_id: str = "alex", tracker: str = ALEX_PHONE) -> Signal:
    return phone(SignalKind.GUEST_HOME, clock, guest_id, tracker)


def away(clock: str, guest_id: str = "alex", tracker: str = ALEX_PHONE) -> Signal:
    return phone(SignalKind.GUEST_AWAY, clock, guest_id, tracker)


def test_phone_home_starts_a_certain_visit():
    engine = Engine(Settings(), guests=[ALEX, SAM])

    changes = engine.handle(home("14:00"))

    (change,) = changes
    visit = change.entry
    assert change.kind is ChangeKind.OPENED
    assert visit.kind is EntryKind.VISIT
    assert visit.certainty is Certainty.CERTAIN
    assert visit.start == at("14:00")
    assert visit.end is None
    assert visit.guests == [{"id": "alex", "name": "Alex"}]
    assert visit.reason.code == "guest_phone"
    assert [s.kind for s in visit.signals] == [SignalKind.GUEST_HOME]
    assert engine.active_entries() == [visit]
    assert engine.next_deadline() is None


def test_phone_of_an_unknown_guest_starts_nothing():
    engine = Engine(Settings(), guests=[ALEX])

    assert engine.handle(home("14:00", "nobody", "device_tracker.other")) == []
    assert engine.active_entries() == []


def test_phone_away_for_the_grace_period_ends_the_visit_at_the_moment_it_went_away():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]

    changes = engine.handle(away("15:00"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.SIGNAL_ADDED, visit)]
    assert engine.next_deadline() == at("15:05")
    assert engine.advance(at("15:04:59")) == []
    changes = engine.advance(at("15:05"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.CLOSED, visit)]
    assert visit.end == at("15:00")
    assert visit.end_reason.code == "guests_left"
    assert engine.active_entries() == []


def test_phone_back_within_the_grace_period_cancels_the_leave():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(away("15:00"))

    changes = engine.handle(home("15:04:59"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.SIGNAL_ADDED, visit)]
    assert engine.next_deadline() is None
    assert engine.advance(at("18:00")) == []
    assert visit.open
    engine.handle(away("18:00"))
    engine.advance(at("18:05"))
    assert visit.end == at("18:00")


def test_phone_back_exactly_at_the_end_of_the_grace_period_is_a_new_visit():
    engine = Engine(Settings(), guests=[ALEX])
    (first,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(away("15:00"))

    changes = engine.handle(home("15:05"))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED, ChangeKind.OPENED]
    second = changes[1].entry
    assert first.end == at("15:00")
    assert second is not first
    assert second.start == at("15:05")


def test_second_guest_phone_joins_the_open_certain_visit():
    engine = Engine(Settings(), guests=[ALEX, SAM])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]

    changes = engine.handle(home("14:10", "sam", SAM_PHONE))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.SIGNAL_ADDED, visit)]
    assert visit.guests == [{"id": "alex", "name": "Alex"}, {"id": "sam", "name": "Sam"}]
    assert len(engine.active_entries()) == 1


def test_visit_with_two_guests_ends_when_the_last_phone_left():
    engine = Engine(Settings(), guests=[ALEX, SAM])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(home("14:10", "sam", SAM_PHONE))

    engine.handle(away("14:20"))
    (left,) = engine.advance(at("23:00"))  # Alex is gone after the grace period, the visit goes on with Sam
    assert left.kind is ChangeKind.GUEST_LEFT
    assert visit.open
    engine.handle(away("23:30", "sam", SAM_PHONE))

    assert engine.next_deadline() == at("23:35")
    engine.advance(at("23:35"))
    assert visit.end == at("23:30")
    assert visit.end_reason.code == "guests_left"


def test_guest_with_two_phones_stays_until_both_left():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(home("14:01", tracker=ALEX_TABLET))

    engine.handle(away("14:20"))
    assert engine.next_deadline() is None
    engine.handle(away("14:25", tracker=ALEX_TABLET))
    engine.advance(at("14:30"))

    assert visit.end == at("14:25")
    assert visit.guests == [{"id": "alex", "name": "Alex"}]


def test_guest_phone_turns_an_open_uncertain_visit_into_a_certain_one():
    engine = Engine(Settings(), guests=[ALEX])
    engine.handle(signal(SignalKind.RING, "14:00", "event.doorbell"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01", "binary_sensor.front_door"))
    (visit,) = engine.active_entries()
    assert visit.certainty is Certainty.UNCERTAIN

    changes = engine.handle(home("14:03"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.SIGNAL_ADDED, visit)]
    assert visit.certainty is Certainty.CERTAIN
    assert visit.guests == [{"id": "alex", "name": "Alex"}]
    assert visit.start == at("14:00")
    assert visit.reason.code == "ring_then_door"
    assert engine.active_entries() == [visit]


def test_upgraded_visit_ends_by_the_phone_rule_not_by_the_door():
    engine = Engine(Settings(), guests=[ALEX])
    engine.handle(signal(SignalKind.RING, "14:00", "event.doorbell"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01", "binary_sensor.front_door"))
    (visit,) = engine.active_entries()
    engine.handle(home("14:03"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:30", "binary_sensor.front_door"))

    assert engine.next_deadline() is None
    assert engine.advance(at("20:00")) == []
    engine.handle(away("21:00"))
    engine.advance(at("21:05"))

    assert visit.end == at("21:00")
    assert visit.end_reason.code == "guests_left"


def test_resident_signal_does_not_turn_a_certain_visit_into_a_resident_arrival():
    engine = Engine(Settings(), guests=[ALEX])
    engine.handle(signal(SignalKind.RING, "14:00", "event.doorbell"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01", "binary_sensor.front_door"))
    (visit,) = engine.active_entries()
    engine.handle(home("14:02"))

    assert engine.handle(signal(SignalKind.RESIDENT, "14:03", "action")) == []
    assert visit.kind is EntryKind.VISIT


def test_door_and_presence_signals_are_logged_in_a_phone_visit():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]

    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:30", "binary_sensor.front_door"))

    assert [(c.kind, c.entry) for c in changes] == [(ChangeKind.SIGNAL_ADDED, visit)]


def test_ring_and_door_while_a_certain_visit_is_open_join_that_visit():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]

    engine.handle(signal(SignalKind.RING, "14:01", "event.doorbell"))
    changes = engine.handle(signal(SignalKind.DOOR_OPEN, "14:02", "binary_sensor.front_door"))

    assert [c.kind for c in changes] == [ChangeKind.CLOSED, ChangeKind.SIGNAL_ADDED]
    assert changes[0].entry.kind is EntryKind.PENDING_RING
    assert changes[1].entry is visit
    assert engine.active_entries() == [visit]
    assert [s.kind for s in visit.signals] == [
        SignalKind.GUEST_HOME,
        SignalKind.RING,
        SignalKind.DOOR_OPEN,
    ]


def test_removing_a_guest_ends_its_open_visit_after_the_grace_period():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]

    engine.set_guests([])

    assert engine.next_deadline() == at("14:00") + timedelta(minutes=5)
    engine.advance(at("14:05"))
    assert visit.end == at("14:00")
    assert visit.end_reason.code == "guests_left"


def test_open_certain_visit_restored_from_storage_keeps_its_deadline():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(away("15:00"))

    restored = Engine(Settings(), guests=[ALEX], entries=[type(visit).from_dict(visit.to_dict())])

    assert restored.next_deadline() == at("15:05")


def test_guest_present_at_start_opens_a_certain_visit_with_its_own_reason():
    engine = Engine(Settings(), guests=[ALEX])

    (change,) = engine.guest_present("alex", ALEX_PHONE, at("14:00"))

    visit = change.entry
    assert change.kind is ChangeKind.OPENED
    assert visit.certainty is Certainty.CERTAIN
    assert visit.start == at("14:00")
    assert visit.guests == [{"id": "alex", "name": "Alex"}]
    assert visit.reason.code == "guest_phone_at_start"
    assert [(s.kind, s.source) for s in visit.signals] == [(SignalKind.GUEST_HOME, ALEX_PHONE)]
    assert engine.active_entries() == [visit]


def test_guest_present_does_nothing_when_an_open_visit_has_the_guest():
    engine = Engine(Settings(), guests=[ALEX])
    (opened,) = engine.handle(home("13:00"))

    assert engine.guest_present("alex", ALEX_PHONE, at("14:00")) == []
    assert engine.active_entries() == [opened.entry]
    assert len(opened.entry.signals) == 1


def test_guest_present_does_nothing_for_a_restored_visit_with_the_guest():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    restored = Engine(Settings(), guests=[ALEX], entries=[Entry.from_dict(visit.to_dict())])

    assert restored.guest_present("alex", ALEX_PHONE, at("14:00")) == []
    assert len(restored.active_entries()) == 1


def test_guest_present_cancels_the_pending_leave_of_a_restored_visit():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    visit.signals.append(away("13:58"))
    restored = Engine(Settings(), guests=[ALEX], entries=[Entry.from_dict(visit.to_dict())])
    assert restored.next_deadline() == at("14:03")

    (change,) = restored.guest_present("alex", ALEX_PHONE, at("14:00"))

    assert change.kind is ChangeKind.SIGNAL_ADDED
    assert [(s.kind, s.time) for s in change.entry.signals][-1] == (SignalKind.GUEST_HOME, at("14:00"))
    assert restored.next_deadline() is None
    assert restored.advance(at("15:00")) == []


def test_guest_present_after_the_grace_period_closes_the_old_visit_and_opens_a_new_one():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    visit.signals.append(away("13:30"))
    restored = Engine(Settings(), guests=[ALEX], entries=[Entry.from_dict(visit.to_dict())])

    closed, opened = restored.guest_present("alex", ALEX_PHONE, at("14:00"))

    assert closed.kind is ChangeKind.CLOSED
    assert closed.entry.end == at("13:30")
    assert opened.kind is ChangeKind.OPENED
    assert opened.entry.reason.code == "guest_phone_at_start"


def test_guest_present_joins_an_open_visit_that_lacks_the_guest():
    engine = Engine(Settings(), guests=[ALEX, SAM])
    (opened,) = engine.handle(home("13:00", "sam", SAM_PHONE))

    (change,) = engine.guest_present("alex", ALEX_PHONE, at("14:00"))

    assert change.kind is ChangeKind.SIGNAL_ADDED
    assert change.entry is opened.entry
    assert [g["name"] for g in opened.entry.guests] == ["Sam", "Alex"]


def test_guest_present_ignores_an_unknown_guest():
    engine = Engine(Settings(), guests=[ALEX])

    assert engine.guest_present("nobody", "device_tracker.other", at("14:00")) == []


def test_guest_absent_ends_a_restored_visit_after_the_phone_grace():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    restored = Engine(Settings(), guests=[ALEX], entries=[Entry.from_dict(visit.to_dict())])

    (change,) = restored.guest_absent("alex", ALEX_PHONE, at("14:00"))

    assert change.kind is ChangeKind.SIGNAL_ADDED
    assert [(s.kind, s.time) for s in change.entry.signals][-1] == (SignalKind.GUEST_AWAY, at("14:00"))
    assert restored.next_deadline() == at("14:05")
    (closed,) = restored.advance(at("14:05"))
    assert closed.kind is ChangeKind.CLOSED
    assert closed.entry.end == at("14:00")
    assert closed.entry.end_reason.code == "guests_left"


def test_guest_absent_does_nothing_when_the_phone_was_not_home_in_the_visit():
    engine = Engine(Settings(), guests=[ALEX])
    engine.handle(home("13:00"))
    engine.handle(away("13:10"))

    assert engine.guest_absent("alex", ALEX_PHONE, at("14:00")) == []
    assert engine.guest_absent("alex", ALEX_TABLET, at("14:00")) == []
    assert engine.guest_absent("nobody", "device_tracker.other", at("14:00")) == []
    assert engine.next_deadline() == at("13:15")
