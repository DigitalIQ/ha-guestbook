from custom_components.guestbook.core import Certainty, EntryKind, Guest, Settings, manual_visit, normalize_name

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
