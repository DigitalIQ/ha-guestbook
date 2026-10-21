from datetime import timedelta

from custom_components.guestbook.core import Engine, Entry, Guest, Settings, Signal, SignalKind
from custom_components.guestbook.core.engine import MAX_SIGNALS

from .helpers import at, signal
from .test_guest_phone import ALEX, ALEX_PHONE, home

PHONE_GUEST = Guest("alex", "Alex", [ALEX_PHONE])


def uncertain_visit(engine: Engine) -> Entry:
    engine.handle(signal(SignalKind.RING, "14:00", "event.doorbell"))
    return engine.handle(signal(SignalKind.DOOR_OPEN, "14:01", "binary_sensor.front_door"))[-1].entry


def flood(engine: Engine, count: int, kind: SignalKind = SignalKind.PRESENCE_ON) -> None:
    start = at("14:02")
    for i in range(count):
        engine.handle(Signal(kind, start + timedelta(seconds=i), "binary_sensor.hall"))


def test_signals_of_an_open_visit_are_capped_and_the_dropped_ones_are_counted():
    engine = Engine(Settings(), guests=[])
    visit = uncertain_visit(engine)

    flood(engine, MAX_SIGNALS + 250, SignalKind.PRESENCE_ON)

    assert len(visit.signals) == MAX_SIGNALS
    assert visit.dropped_signals == 252  # the ring and the door opening plus 1000 + 250 flood signals, 1000 kept
    assert visit.dropped_signals + len(visit.signals) == 2 + MAX_SIGNALS + 250


def test_the_oldest_ordinary_signals_go_first_and_the_start_of_the_visit_stays():
    engine = Engine(Settings(), guests=[])
    visit = uncertain_visit(engine)

    flood(engine, MAX_SIGNALS + 10)

    assert visit.signals[0].kind is SignalKind.RING
    assert visit.signals[1].kind is SignalKind.DOOR_OPEN  # the signal that made the ring a visit
    assert visit.signals[2].time == at("14:02") + timedelta(seconds=12)
    assert visit.signals[-1].time == at("14:02") + timedelta(seconds=MAX_SIGNALS + 9)


def test_phone_signals_are_never_dropped():
    engine = Engine(Settings(), guests=[ALEX])
    visit = engine.handle(home("14:00"))[0].entry
    flood(engine, 10)
    engine.handle(Signal(SignalKind.GUEST_AWAY, at("14:03"), ALEX_PHONE, guest_id="alex"))
    engine.handle(home("14:04"))

    flood(engine, MAX_SIGNALS + 100)

    kinds = [s.kind for s in visit.signals]
    assert kinds.count(SignalKind.GUEST_HOME) == 2
    assert kinds.count(SignalKind.GUEST_AWAY) == 1
    assert len(visit.signals) == MAX_SIGNALS


def test_a_visit_made_only_of_protected_signals_is_not_truncated():
    engine = Engine(Settings(), guests=[ALEX])
    visit = engine.handle(home("14:00"))[0].entry

    for i in range(MAX_SIGNALS + 5):
        engine.handle(
            Signal(
                SignalKind.GUEST_AWAY if i % 2 else SignalKind.GUEST_HOME,
                at("14:01") + timedelta(seconds=i),
                ALEX_PHONE,
                guest_id="alex",
            )
        )

    assert len(visit.signals) == MAX_SIGNALS + 6
    assert visit.dropped_signals == 0


def test_a_capped_visit_still_ends_by_the_door_rule():
    engine = Engine(Settings(), guests=[])
    visit = uncertain_visit(engine)
    flood(engine, MAX_SIGNALS + 10)
    engine.handle(signal(SignalKind.DOOR_OPEN, "16:00", "binary_sensor.front_door"))

    engine.advance(at("16:10"))

    assert visit.end == at("16:00")
    assert visit.end_reason.code == "door_then_quiet"


def test_the_dropped_count_survives_a_json_round_trip():
    engine = Engine(Settings(), guests=[])
    visit = uncertain_visit(engine)
    flood(engine, MAX_SIGNALS + 3)

    assert visit.dropped_signals == 5
    assert Entry.from_dict(visit.to_dict()).dropped_signals == 5
