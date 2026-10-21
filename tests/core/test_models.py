import json
from datetime import timedelta

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
    )

    restored = Entry.from_dict(json.loads(json.dumps(entry.to_dict())))

    assert restored == entry


def test_open_entry_without_optional_parts_survives_a_round_trip():
    entry = Entry(id="e2", kind=EntryKind.PENDING_RING, start=at("14:00"))

    restored = Entry.from_dict(json.loads(json.dumps(entry.to_dict())))

    assert restored == entry
    assert restored.open


def test_settings_survive_a_round_trip_with_custom_values():
    settings = Settings(ring_window=timedelta(minutes=2), max_duration=timedelta(hours=6))

    assert Settings.from_dict(json.loads(json.dumps(settings.to_dict()))) == settings


def test_guest_survives_a_round_trip():
    guest = Guest(id="g1", name="Alex", trackers=["device_tracker.alex_phone"])

    assert Guest.from_dict(guest.to_dict()) == guest
