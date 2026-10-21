from custom_components.guestbook.core import (
    MAX_GUEST_NAME,
    Certainty,
    EntryKind,
    Guest,
    Settings,
    clean_guest_name,
    manual_visit,
    normalize_name,
)

from .helpers import at

ALEX = Guest("alex-id", "Alex", ["device_tracker.alex_phone"])


def test_names_are_compared_trimmed_and_case_insensitive():
    assert normalize_name("  ALEX ") == normalize_name("alex")
    assert normalize_name("Straße") == normalize_name("STRASSE")


def test_manual_visit_is_a_closed_certain_visit_with_the_manual_reason():
    entry = manual_visit(["Sam"], [ALEX], at("10:00"), at("11:00"), "Brought cake", Settings())

    assert entry.kind is EntryKind.VISIT
    assert entry.certainty is Certainty.CERTAIN
    assert (entry.start, entry.end) == (at("10:00"), at("11:00"))
    assert entry.reason.code == "manual"
    assert entry.notes == ["Brought cake"]
    assert Settings.from_dict(entry.settings) == Settings()
    assert entry.signals == []


def test_manual_visit_uses_a_matching_guest_profile_in_any_case_and_keeps_free_names():
    entry = manual_visit([" alex ", "Sam", "ALEX", "", "  "], [ALEX], at("10:00"), at("11:00"), None, Settings())

    assert entry.guests == [{"id": "alex-id", "name": "Alex"}, {"id": "", "name": "Sam"}]
    assert entry.notes == []


def test_each_manual_visit_gets_its_own_id():
    first = manual_visit([], [], at("10:00"), at("11:00"), None, Settings())
    second = manual_visit([], [], at("10:00"), at("11:00"), None, Settings())

    assert first.id != second.id


def test_guest_names_are_trimmed_and_cut_to_the_maximum_length():
    assert MAX_GUEST_NAME == 64
    assert clean_guest_name("  Alex  ") == "Alex"
    assert clean_guest_name("x" * 100) == "x" * 64
    assert clean_guest_name("  " + "y" * 70) == "y" * 64
    assert clean_guest_name(" " * 3) == ""


def test_manual_visit_cuts_long_free_names_and_counts_equal_cut_names_once():
    long = "N" * 80
    entry = manual_visit([long, "N" * 64, "N" * 90], [], at("10:00"), at("11:00"), None, Settings())

    assert entry.guests == [{"id": "", "name": "N" * 64}]
