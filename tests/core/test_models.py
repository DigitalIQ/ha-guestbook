import json
from datetime import timedelta

import pytest

from custom_components.guestbook.core import (
    Certainty,
    Correction,
    Entry,
    EntryKind,
    Guest,
    Reason,
    Settings,
    Signal,
    SignalKind,
)

from .helpers import at


def test_entry_survives_a_json_round_trip():
    entry = Entry(
        id="e1",
        kind=EntryKind.VISIT,
        start=at("14:00"),
        end=at("15:30"),
        certainty=Certainty.UNCERTAIN,
        guests=[{"id": "g1", "name": "Alex"}],
        signals=[
            Signal(SignalKind.RING, at("14:00"), "event.doorbell"),
            Signal(SignalKind.GUEST_HOME, at("14:01"), "device_tracker.alex_phone", state="home", guest_id="g1"),
        ],
        reason=Reason("ring_then_door", "Ring followed by door opening"),
        end_reason=Reason("door_then_quiet", "Quiet period after a door opening"),
        correction=Correction(
            kind="visit", time=at("16:00"), source="action", guest_name="Alex", start=at("13:55"), note="Dinner"
        ),
        notes=["Brought wine"],
        settings=Settings().to_dict(),
        rule_state={"deadline": at("14:05").isoformat()},
        question_token="tok_en-1",
        dropped_signals=4,
    )

    restored = Entry.from_dict(json.loads(json.dumps(entry.to_dict())))

    assert restored == entry


def test_open_entry_without_optional_parts_survives_a_round_trip():
    entry = Entry(
        id="e2", kind=EntryKind.PENDING_RING, start=at("14:00"), rule_state={"deadline": at("14:05").isoformat()}
    )

    restored = Entry.from_dict(json.loads(json.dumps(entry.to_dict())))

    assert restored == entry
    assert restored.open


def test_settings_survive_a_round_trip_with_custom_values():
    settings = Settings(ring_window=timedelta(minutes=2), max_duration=timedelta(hours=6))

    assert Settings.from_dict(json.loads(json.dumps(settings.to_dict()))) == settings


def test_guest_survives_a_round_trip():
    guest = Guest(id="g1", name="Alex", trackers=["device_tracker.alex_phone"])

    assert Guest.from_dict(guest.to_dict()) == guest


def test_a_pending_ring_without_a_usable_deadline_cannot_be_read():
    ring = Entry(
        id="r", kind=EntryKind.PENDING_RING, start=at("14:00"), rule_state={"deadline": at("14:05").isoformat()}
    )
    Entry.from_dict(ring.to_dict())  # the valid one reads fine

    for rule_state in (
        {},
        {"deadline": None},
        {"deadline": "soon"},
        {"deadline": "2026-10-21T14:05:00"},
        {"deadline": 5},
    ):
        broken = {**ring.to_dict(), "rule_state": rule_state}
        with pytest.raises(ValueError, match="deadline"):
            Entry.from_dict(broken)


def test_a_closed_pending_ring_needs_no_deadline():
    done = Entry(id="r", kind=EntryKind.PENDING_RING, start=at("14:00"), end=at("14:01"))

    assert Entry.from_dict(done.to_dict()) == done


def test_guests_of_a_stored_entry_need_an_id_and_a_name():
    entry = Entry(id="v", kind=EntryKind.VISIT, start=at("14:00"), guests=[{"id": "g", "name": "Alex"}])
    for guests in ([{"name": "Alex"}], [{"id": "g"}], ["Alex"], [{"id": None, "name": "Alex"}]):
        with pytest.raises(ValueError):
            Entry.from_dict({**entry.to_dict(), "guests": guests})
