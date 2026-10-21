from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from custom_components.guestbook.core import (
    Certainty,
    Correction,
    Entry,
    EntryKind,
    Reason,
    Signal,
    SignalKind,
)
from custom_components.guestbook.core.render import render_description, render_title

from .helpers import at, signal

BERLIN = ZoneInfo("Europe/Berlin")  # UTC+2 on the test day
NAMES = {
    "event.front_doorbell": "Front doorbell",
    "binary_sensor.front_door": "Front door",
    "binary_sensor.living_room": "Living room presence",
    "binary_sensor.hall": "Hall presence",
    "lock.front_door_lock": "Front door lock",
    "device_tracker.alex_phone": "Alex phone",
}


def visit(*signals: Signal, **kwargs) -> Entry:
    fields = {
        "id": "v1",
        "kind": EntryKind.VISIT,
        "start": at("12:00"),
        "end": at("13:00"),
        "certainty": Certainty.UNCERTAIN,
        "signals": list(signals),
    } | kwargs
    return Entry(**fields)


def describe(entry: Entry, language: str = "en") -> list[str]:
    return render_description(entry, language, NAMES, BERLIN).splitlines()


def test_every_signal_is_listed_in_time_order_with_local_time_and_readable_name():
    entry = visit(
        signal(SignalKind.DOOR_OPEN, "12:01", "binary_sensor.front_door"),
        signal(SignalKind.RING, "12:00", "event.front_doorbell"),
        Signal(SignalKind.LOCK, at("12:05"), "lock.front_door_lock", "unlocked"),
        signal(SignalKind.DOOR_CLOSE, "12:02", "binary_sensor.front_door"),
        signal(SignalKind.GUEST_HOME, "12:03", "device_tracker.alex_phone"),
        signal(SignalKind.GUEST_AWAY, "12:55", "device_tracker.alex_phone"),
    )

    assert describe(entry) == [
        "14:00 Front doorbell: ring",
        "14:01 Front door: opened",
        "14:02 Front door: closed",
        "14:03 Alex phone: joined the network",
        "14:05 Front door lock: unlocked",
        "14:55 Alex phone: left the network",
    ]


def test_unknown_entity_is_shown_by_its_entity_id():
    entry = visit(signal(SignalKind.DOOR_OPEN, "12:00", "binary_sensor.garage_door"))

    assert describe(entry) == ["14:00 binary_sensor.garage_door: opened"]


def test_resident_signal_from_the_action_names_the_action_and_its_source_text():
    entry = visit(
        Signal(SignalKind.RESIDENT, at("12:00"), "action", "Garage keypad"),
        Signal(SignalKind.RESIDENT, at("12:01"), "binary_sensor.front_door", "on"),
    )

    assert describe(entry) == [
        "14:00 resident_unlock action: resident signal (Garage keypad)",
        "14:01 Front door: resident signal",
    ]


def test_presence_on_off_pair_becomes_one_line_with_a_range():
    entry = visit(
        signal(SignalKind.PRESENCE_ON, "12:02", "binary_sensor.living_room"),
        signal(SignalKind.DOOR_OPEN, "12:10", "binary_sensor.front_door"),
        signal(SignalKind.PRESENCE_OFF, "12:40", "binary_sensor.living_room"),
    )

    assert describe(entry) == [
        "Living room presence 14:02–14:40",
        "14:10 Front door: opened",
    ]


def test_presence_stretches_are_condensed_per_sensor():
    entry = visit(
        signal(SignalKind.PRESENCE_ON, "12:02", "binary_sensor.living_room"),
        signal(SignalKind.PRESENCE_ON, "12:03", "binary_sensor.hall"),
        signal(SignalKind.PRESENCE_OFF, "12:04", "binary_sensor.living_room"),
        signal(SignalKind.PRESENCE_OFF, "12:05", "binary_sensor.hall"),
        signal(SignalKind.PRESENCE_ON, "12:30", "binary_sensor.living_room"),
        signal(SignalKind.PRESENCE_OFF, "12:45", "binary_sensor.living_room"),
    )

    assert describe(entry) == [
        "Living room presence 14:02–14:04",
        "Hall presence 14:03–14:05",
        "Living room presence 14:30–14:45",
    ]


def test_presence_that_is_still_on_has_an_open_end():
    entry = visit(signal(SignalKind.PRESENCE_ON, "12:02", "binary_sensor.living_room"), end=None)

    assert describe(entry) == ["Living room presence from 14:02"]


def test_presence_off_without_an_on_in_the_visit_is_a_stretch_that_ends():
    entry = visit(signal(SignalKind.PRESENCE_OFF, "12:20", "binary_sensor.hall"))

    assert describe(entry) == ["Hall presence until 14:20"]


def test_a_long_log_is_not_cut():
    signals = [
        Signal(SignalKind.DOOR_OPEN, at("12:00") + timedelta(seconds=i), "binary_sensor.front_door") for i in range(600)
    ]

    assert len(describe(visit(*signals))) == 600


def test_description_is_german_when_the_language_is_german():
    entry = visit(
        signal(SignalKind.RING, "12:00", "event.front_doorbell"),
        signal(SignalKind.DOOR_OPEN, "12:01", "binary_sensor.front_door"),
        signal(SignalKind.PRESENCE_ON, "12:02", "binary_sensor.living_room"),
        signal(SignalKind.PRESENCE_OFF, "12:40", "binary_sensor.living_room"),
        signal(SignalKind.GUEST_HOME, "12:03", "device_tracker.alex_phone"),
        Signal(SignalKind.LOCK, at("12:05"), "lock.front_door_lock", "locked"),
        signal(SignalKind.PRESENCE_ON, "12:50", "binary_sensor.hall"),
        end=None,
    )

    assert describe(entry, "de") == [
        "14:00 Front doorbell: geklingelt",
        "14:01 Front door: geöffnet",
        "Living room presence 14:02–14:40",
        "14:03 Alex phone: im Netzwerk angekommen",
        "14:05 Front door lock: abgeschlossen",
        "Hall presence ab 14:50",
    ]


def test_regional_german_is_german_and_unknown_languages_fall_back_to_english():
    entry = visit(signal(SignalKind.DOOR_OPEN, "12:01", "binary_sensor.front_door"))

    assert describe(entry, "de-AT") == ["14:01 Front door: geöffnet"]
    assert describe(entry, "fr") == ["14:01 Front door: opened"]


def test_description_ends_with_start_and_end_reason():
    entry = visit(
        signal(SignalKind.RING, "12:00", "event.front_doorbell"),
        reason=Reason("ring_then_door", "x"),
        end_reason=Reason("door_then_quiet", "y"),
    )

    assert describe(entry) == [
        "14:00 Front doorbell: ring",
        "",
        "Started: ring followed by a door opening or presence",
        "Ended: door opening followed by a quiet period",
    ]
    assert describe(entry, "de")[2:] == [
        "Beginn: Klingeln, danach Türöffnung oder Anwesenheit",
        "Ende: Türöffnung, danach Ruhe",
    ]


def test_unknown_reason_code_falls_back_to_the_detail_text():
    entry = visit(reason=Reason("new_rule", "Something new"))

    assert describe(entry) == ["Started: Something new"]


def test_description_lists_the_correction_and_notes():
    correction = Correction(
        kind="visit",
        time=datetime(2026, 10, 21, 13, 30, tzinfo=UTC),
        source="action",
        guest_name="Alex",
        start=at("11:55"),
        end=at("13:10"),
        note="Came to fix the sink",
    )
    entry = visit(
        signal(SignalKind.RING, "12:00", "event.front_doorbell"), correction=correction, notes=["Brought tools"]
    )

    assert describe(entry) == [
        "14:00 Front doorbell: ring",
        "",
        "Correction (action, 2026-10-21 15:30): visit, guest Alex, start 13:55, end 15:10, note: Came to fix the sink",
        "Notes:",
        "- Brought tools",
    ]
    assert describe(entry, "de")[2:] == [
        "Korrektur (Aktion, 2026-10-21 15:30): Besuch, Gast Alex, Beginn 13:55, Ende 15:10, "
        "Notiz: Came to fix the sink",
        "Notizen:",
        "- Brought tools",
    ]


def test_entry_without_signals_reason_or_notes_has_an_empty_description():
    assert render_description(visit(), "en", NAMES, BERLIN) == ""


def test_titles_name_the_guests_or_the_uncertainty():
    named = visit(guests=[{"id": "a", "name": "Alex"}, {"id": "s", "name": "Sam"}])
    ring = visit(kind=EntryKind.UNANSWERED_RING, certainty=None)

    assert render_title(named, "en") == "Visit: Alex, Sam"
    assert render_title(named, "de") == "Besuch: Alex, Sam"
    assert render_title(visit(), "en") == "Visit (uncertain)"
    assert render_title(visit(), "de") == "Besuch (unsicher)"
    assert render_title(visit(certainty=Certainty.CERTAIN), "en") == "Visit"
    assert render_title(ring, "en") == "Unanswered ring"
    assert render_title(ring, "de") == "Klingeln ohne Einlass"
    assert render_title(ring, "fr") == "Unanswered ring"
