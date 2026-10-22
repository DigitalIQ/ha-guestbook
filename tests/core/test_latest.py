from custom_components.guestbook.core import Correction, CorrectionKind, Entry, EntryKind, latest_entry

from .helpers import at


def entry(entry_id: str, clock: str, kind: EntryKind = EntryKind.VISIT, end: str | None = None) -> Entry:
    return Entry(id=entry_id, kind=kind, start=at(clock), end=at(end) if end else None)


def test_no_entries_means_no_latest_entry():
    assert latest_entry([]) is None


def test_the_latest_entry_is_the_one_with_the_most_recent_start():
    older = entry("older", "10:00", end="10:30")
    newer = entry("newer", "12:00", end="12:30")

    assert latest_entry([newer, older]) is newer
    assert latest_entry([older, newer]) is newer


def test_open_and_closed_visits_both_count():
    closed = entry("closed", "10:00", end="10:30")
    open_visit = entry("open", "09:00")

    assert latest_entry([open_visit, closed]) is closed
    assert latest_entry([closed, entry("open2", "11:00")]).id == "open2"


def test_unanswered_rings_count_like_visits():
    visit = entry("visit", "10:00", end="10:30")
    ring = entry("ring", "11:00", EntryKind.UNANSWERED_RING, end="11:06")

    assert latest_entry([visit, ring]) is ring


def test_pending_rings_and_resident_arrivals_are_never_the_latest_entry():
    visit = entry("visit", "10:00", end="10:30")
    pending = entry("pending", "11:00", EntryKind.PENDING_RING)
    resident = entry("resident", "12:00", EntryKind.RESIDENT_ARRIVAL, end="12:01")

    assert latest_entry([visit, pending, resident]) is visit
    assert latest_entry([pending, resident]) is None


def test_the_stored_kind_decides_not_a_correction():
    corrected_to_resident = entry("corrected", "12:00", end="12:30")
    corrected_to_resident.correction = Correction(CorrectionKind.RESIDENT, at("12:31"), "action")
    resident_made_visit = entry("promoted", "13:00", EntryKind.RESIDENT_ARRIVAL, end="13:01")
    resident_made_visit.correction = Correction(CorrectionKind.VISIT, at("13:02"), "action")
    visit = entry("visit", "10:00", end="10:30")

    assert latest_entry([visit, corrected_to_resident]) is corrected_to_resident
    assert latest_entry([visit, resident_made_visit]) is visit


def test_the_start_is_the_stored_start_not_a_corrected_start():
    moved = entry("moved", "10:00", end="10:30")
    moved.correction = Correction(CorrectionKind.VISIT, at("10:40"), "action", start=at("15:00"), end=at("16:00"))
    other = entry("other", "11:00", end="11:30")

    assert latest_entry([moved, other]) is other


def test_entries_with_the_same_start_resolve_to_the_one_stored_last():
    first = entry("first", "10:00", end="10:30")
    second = entry("second", "10:00", end="10:30")

    assert latest_entry([first, second]) is second
