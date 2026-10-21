from custom_components.guestbook.core import ChangeKind, Engine, Guest, Settings

from .helpers import at
from .test_guest_phone import ALEX, ALEX_PHONE, ALEX_TABLET, SAM, SAM_PHONE, away, home

# --- a guest with two phones that are both home at startup ---------------------------------------------------------


def test_both_phones_of_a_guest_that_are_home_at_startup_are_recorded():
    engine = Engine(Settings(), guests=[ALEX])

    engine.guest_present("alex", ALEX_PHONE, at("14:00"))
    changes = engine.guest_present("alex", ALEX_TABLET, at("14:00"))

    (visit,) = engine.active_entries()
    assert [c.kind for c in changes] == [ChangeKind.SIGNAL_ADDED]
    assert [(s.source, s.kind.value) for s in visit.signals] == [
        (ALEX_PHONE, "guest_home"),
        (ALEX_TABLET, "guest_home"),
    ]


def test_the_visit_continues_while_the_second_phone_of_the_guest_is_home():
    engine = Engine(Settings(), guests=[ALEX])
    engine.guest_present("alex", ALEX_PHONE, at("14:00"))
    engine.guest_present("alex", ALEX_TABLET, at("14:00"))

    engine.handle(away("14:30"))

    assert engine.next_deadline() is None
    assert engine.advance(at("16:00")) == []
    (visit,) = engine.active_entries()
    assert visit.open


def test_the_visit_ends_when_the_last_phone_of_the_guest_has_left_for_the_grace_period():
    engine = Engine(Settings(), guests=[ALEX])
    engine.guest_present("alex", ALEX_PHONE, at("14:00"))
    engine.guest_present("alex", ALEX_TABLET, at("14:00"))
    engine.handle(away("14:30"))
    engine.handle(away("14:40", tracker=ALEX_TABLET))

    assert engine.next_deadline() == at("14:45")
    (closed,) = engine.advance(at("14:45"))

    assert closed.kind is ChangeKind.CLOSED
    assert closed.entry.end == at("14:40")


def test_a_phone_of_the_guest_that_the_restored_visit_never_saw_is_added_to_it():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    restored = Engine(Settings(), guests=[ALEX], entries=[visit])

    (change,) = restored.guest_present("alex", ALEX_TABLET, at("14:00"))

    assert change.kind is ChangeKind.SIGNAL_ADDED
    assert change.signal.source == ALEX_TABLET
    restored.handle(away("14:10"))  # the first phone leaves, the tablet is still home
    assert restored.next_deadline() is None


def test_a_phone_that_is_already_recorded_as_home_is_not_added_twice():
    engine = Engine(Settings(), guests=[ALEX])
    engine.guest_present("alex", ALEX_PHONE, at("14:00"))

    assert engine.guest_present("alex", ALEX_PHONE, at("14:01")) == []


# --- who is present in a visit that goes on ------------------------------------------------------------------------


def two_guest_visit() -> Engine:
    engine = Engine(Settings(), guests=[ALEX, SAM])
    engine.handle(home("14:00"))
    engine.handle(home("14:10", "sam", SAM_PHONE))
    return engine


def test_every_guest_of_a_visit_is_present_while_it_starts():
    engine = two_guest_visit()

    (visit,) = engine.active_entries()

    assert visit.present_guest_ids == {"alex", "sam"}


def test_a_guest_who_left_stays_present_during_the_phone_grace_period():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()

    engine.handle(away("14:30"))
    assert engine.advance(at("14:34:59")) == []

    assert visit.present_guest_ids == {"alex", "sam"}


def test_a_guest_who_left_is_no_longer_present_after_the_grace_period_but_stays_in_the_visit():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()
    engine.handle(away("14:30"))

    assert engine.next_deadline() == at("14:35")
    (change,) = engine.advance(at("14:35"))

    assert change.kind is ChangeKind.GUEST_LEFT
    assert change.entry is visit
    assert visit.present_guest_ids == {"sam"}
    assert [g["id"] for g in visit.guests] == ["alex", "sam"]
    assert visit.open
    assert engine.next_deadline() is None


def test_a_guest_who_left_is_present_again_when_the_phone_returns():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()
    engine.handle(away("14:30"))
    engine.advance(at("14:35"))

    engine.handle(home("15:00"))

    assert visit.present_guest_ids == {"alex", "sam"}
    assert [g["id"] for g in visit.guests] == ["alex", "sam"]


def test_a_phone_back_before_the_grace_period_ended_changes_nothing():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()
    engine.handle(away("14:30"))
    engine.handle(home("14:34"))

    assert engine.advance(at("15:00")) == []
    assert visit.present_guest_ids == {"alex", "sam"}


def test_the_visit_ends_when_the_last_present_guest_left_and_nobody_is_present():
    engine = two_guest_visit()
    engine.handle(away("14:30"))
    engine.advance(at("14:35"))
    engine.handle(away("14:50", "sam", SAM_PHONE))

    (closed,) = engine.advance(at("14:55"))

    assert closed.kind is ChangeKind.CLOSED
    assert closed.entry.end == at("14:50")
    assert closed.entry.end_reason.code == "guests_left"


def test_a_guest_with_two_phones_is_present_until_both_are_away_for_the_grace_period():
    engine = Engine(Settings(), guests=[ALEX, SAM])
    engine.guest_present("alex", ALEX_PHONE, at("14:00"))
    engine.guest_present("alex", ALEX_TABLET, at("14:00"))
    engine.handle(home("14:05", "sam", SAM_PHONE))
    (visit,) = engine.active_entries()

    engine.handle(away("14:10"))
    assert engine.next_deadline() is None
    engine.handle(away("14:20", tracker=ALEX_TABLET))
    engine.advance(at("14:25"))

    assert visit.present_guest_ids == {"sam"}


def test_who_is_present_survives_a_json_round_trip():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()
    engine.handle(away("14:30"))
    engine.advance(at("14:35"))

    restored = Engine(Settings(), guests=[ALEX, SAM], entries=[type(visit).from_dict(visit.to_dict())])

    (again,) = restored.active_entries()
    assert again.present_guest_ids == {"sam"}


def test_a_guest_who_was_removed_from_the_profiles_leaves_the_visit_after_the_grace_period():
    engine = two_guest_visit()
    (visit,) = engine.active_entries()

    engine.set_guests([SAM])

    (change,) = engine.advance(at("14:20"))
    assert change.kind is ChangeKind.GUEST_LEFT
    assert visit.present_guest_ids == {"sam"}


# --- renamed guests ------------------------------------------------------------------------------------------------


def test_a_renamed_guest_who_returns_within_the_grace_period_is_listed_once_with_the_new_name():
    engine = Engine(Settings(), guests=[ALEX])
    (visit,) = [c.entry for c in engine.handle(home("14:00"))]
    engine.handle(away("14:10"))

    engine.set_guests([Guest("alex", "Alexandra", ALEX.trackers)])
    engine.handle(home("14:12"))

    assert visit.guests == [{"id": "alex", "name": "Alexandra"}]
    assert engine.active_entries() == [visit]


def test_a_renamed_guest_found_at_startup_is_listed_once_with_the_new_name():
    visit = Engine(Settings(), guests=[ALEX]).handle(home("13:00"))[0].entry
    renamed = Guest("alex", "Alexandra", ALEX.trackers)
    restored = Engine(Settings(), guests=[renamed], entries=[visit])

    restored.guest_present("alex", ALEX_TABLET, at("14:00"))

    assert visit.guests == [{"id": "alex", "name": "Alexandra"}]
