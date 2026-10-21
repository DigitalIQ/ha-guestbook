from datetime import UTC, datetime

import pytest

from custom_components.guestbook.core import (
    ChangeKind,
    Correction,
    EffectiveKind,
    Engine,
    Entry,
    EntryKind,
    Settings,
    SignalKind,
    effective_end,
    effective_guests,
    effective_kind,
    effective_start,
    render_title,
)

from .helpers import at, signal

NOW = datetime(2026, 10, 21, 15, 0, tzinfo=UTC)


def entry(kind: EntryKind = EntryKind.VISIT, **kwargs) -> Entry:
    return Entry(id="e1", kind=kind, start=at("14:00"), end=at("15:00"), **kwargs)


def correct(kind: str, **kwargs) -> Correction:
    return Correction(kind=kind, time=NOW, source="action", **kwargs)


@pytest.mark.parametrize("kind", list(EntryKind))
def test_entry_without_correction_keeps_the_kind_of_the_decision(kind):
    assert effective_kind(entry(kind)) == EffectiveKind(kind.value)


@pytest.mark.parametrize(
    ("decision", "corrected", "expected"),
    [
        (EntryKind.VISIT, "resident", EffectiveKind.RESIDENT_ARRIVAL),
        (EntryKind.VISIT, "delivery", EffectiveKind.DELIVERY),
        (EntryKind.UNANSWERED_RING, "visit", EffectiveKind.VISIT),
        (EntryKind.RESIDENT_ARRIVAL, "visit", EffectiveKind.VISIT),
        (EntryKind.UNANSWERED_RING, "resident", EffectiveKind.RESIDENT_ARRIVAL),
        (EntryKind.UNANSWERED_RING, "delivery", EffectiveKind.DELIVERY),
        (EntryKind.VISIT, "unknown", EffectiveKind.VISIT),
        (EntryKind.UNANSWERED_RING, "unknown", EffectiveKind.UNANSWERED_RING),
        (EntryKind.RESIDENT_ARRIVAL, "unknown", EffectiveKind.RESIDENT_ARRIVAL),
    ],
)
def test_correction_overrides_the_decision(decision, corrected, expected):
    assert effective_kind(entry(decision, correction=correct(corrected))) == expected


def test_correction_leaves_the_decision_untouched():
    corrected = entry(EntryKind.VISIT, correction=correct("resident"))

    assert corrected.kind is EntryKind.VISIT


def test_effective_guests_are_the_profiles_plus_the_corrected_name():
    visit = entry(guests=[{"id": "s", "name": "Sam"}], correction=correct("visit", guest_name="Alex"))

    assert effective_guests(visit) == ["Sam", "Alex"]


def test_effective_guests_do_not_repeat_a_name_in_any_case():
    visit = entry(guests=[{"id": "a", "name": "Alex"}], correction=correct("visit", guest_name="alex"))

    assert effective_guests(visit) == ["Alex"]


def test_guest_name_only_counts_for_a_visit_correction():
    assert effective_guests(entry(correction=correct("delivery", guest_name="Alex"))) == []
    assert effective_guests(entry(guests=[{"id": "a", "name": "Alex"}])) == ["Alex"]


def test_corrected_times_replace_the_shown_times():
    plain = entry()
    shifted = entry(correction=correct("unknown", start=at("13:50"), end=at("15:10")))

    assert (effective_start(plain), effective_end(plain)) == (at("14:00"), at("15:00"))
    assert (effective_start(shifted), effective_end(shifted)) == (at("13:50"), at("15:10"))


def test_open_entry_has_no_effective_end():
    assert effective_end(Entry(id="e", kind=EntryKind.VISIT, start=at("14:00"))) is None


def test_titles_follow_the_effective_kind():
    ring = entry(EntryKind.UNANSWERED_RING)
    as_visit = entry(EntryKind.UNANSWERED_RING, correction=correct("visit", guest_name="Alex"))
    delivery = entry(EntryKind.VISIT, correction=correct("delivery"))

    assert render_title(ring, "en") == "Unanswered ring"
    assert render_title(as_visit, "en") == "Visit: Alex"
    assert render_title(as_visit, "de") == "Besuch: Alex"
    assert render_title(delivery, "en") == "Delivery"
    assert render_title(delivery, "de") == "Lieferung"


def open_visit(engine: Engine) -> Entry:
    engine.handle(signal(SignalKind.RING, "14:00"))
    engine.handle(signal(SignalKind.DOOR_OPEN, "14:01"))
    (visit,) = engine.active_entries()
    return visit


def test_close_ends_an_open_visit_for_good():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)

    (change,) = engine.close(visit.id, at("14:30"))

    assert change.kind is ChangeKind.CLOSED
    assert change.entry is visit
    assert (visit.end, visit.end_reason.code) == (at("14:30"), "corrected")
    assert engine.active_entries() == []
    assert engine.next_deadline() is None


def test_closed_visit_receives_no_more_signals():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.close(visit.id, at("14:30"))

    assert engine.handle(signal(SignalKind.DOOR_OPEN, "14:40")) == []
    assert [s.kind for s in visit.signals] == [SignalKind.RING, SignalKind.DOOR_OPEN]


def test_close_ignores_unknown_and_already_closed_entries():
    engine = Engine(Settings(), guests=[])
    visit = open_visit(engine)
    engine.close(visit.id, at("14:30"))

    assert engine.close(visit.id, at("14:31")) == []
    assert engine.close("nope", at("14:31")) == []


def test_close_leaves_a_pending_ring_alone():
    engine = Engine(Settings(), guests=[])
    pending = engine.handle(signal(SignalKind.RING, "14:00"))[0].entry

    assert engine.close(pending.id, at("14:01")) == []
    assert engine.active_entries() == [pending]


def test_engine_exposes_its_settings():
    settings = Settings()

    assert Engine(settings, guests=[]).settings is settings
