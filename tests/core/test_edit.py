from datetime import timedelta

import pytest

from custom_components.guestbook.core import (
    Certainty,
    Correction,
    CorrectionKind,
    Entry,
    EntryKind,
    TitleAnswer,
    added_lines,
    parse_title,
    plan_edit,
    render_title,
)

from .helpers import at


def visit(**kwargs) -> Entry:
    fields = {
        "id": "v1",
        "kind": EntryKind.VISIT,
        "start": at("12:00:07").replace(microsecond=123456),
        "end": at("13:00:42"),
        "certainty": Certainty.UNCERTAIN,
    } | kwargs
    return Entry(**fields)


def plan(entry: Entry, **kwargs):
    fields = {
        "summary": render_title(entry, "en"),
        "start": entry.start.replace(microsecond=0),
        "end": entry.end,
        "generated": "12:00 Front doorbell: ring",
        "sent": "12:00 Front doorbell: ring",
    } | kwargs
    return plan_edit(entry, **fields)


@pytest.mark.parametrize(
    ("text", "kind"),
    [
        ("That was me", CorrectionKind.RESIDENT),
        ("that was ME", CorrectionKind.RESIDENT),
        ("War ich", CorrectionKind.RESIDENT),
        ("  das war   ich ", CorrectionKind.RESIDENT),
        ("Resident arrival", CorrectionKind.RESIDENT),
        ("Ankunft eines Bewohners", CorrectionKind.RESIDENT),
        ("Delivery", CorrectionKind.DELIVERY),
        ("LIEFERUNG", CorrectionKind.DELIVERY),
        ("Don't know", CorrectionKind.UNKNOWN),
        ("Don\u2019t know", CorrectionKind.UNKNOWN),
        ("Weiß nicht", CorrectionKind.UNKNOWN),
        ("weiss nicht", CorrectionKind.UNKNOWN),
        ("Visit (uncertain)", CorrectionKind.UNKNOWN),
        ("Besuch (unsicher)", CorrectionKind.UNKNOWN),
        ("Unanswered ring", CorrectionKind.UNKNOWN),
        ("Klingeln ohne Einlass", CorrectionKind.UNKNOWN),
    ],
)
def test_a_known_word_in_english_or_german_decides_the_kind(text, kind):
    assert parse_title(text) == TitleAnswer(kind)


@pytest.mark.parametrize("text", ["Visit", "visit", "Besuch", "Visit:", "Besuch :  "])
def test_visit_without_a_name_is_a_visit_correction_without_guest(text):
    assert parse_title(text) == TitleAnswer(CorrectionKind.VISIT)


@pytest.mark.parametrize(
    ("text", "name"),
    [
        ("Visit: Alex", "Alex"),
        ("besuch: Alex Example", "Alex Example"),
        ("VISIT:Alex", "Alex"),
        ("Alex", "Alex"),
        ("  Alex   ", "Alex"),
        ("Aunt Pat", "Aunt Pat"),
        ("Visit: Alex, Sam", "Alex, Sam"),
    ],
)
def test_a_name_or_a_visit_prefix_with_a_name_is_a_visit_of_that_guest(text, name):
    assert parse_title(text) == TitleAnswer(CorrectionKind.VISIT, name)


def test_the_guest_name_is_cut_to_the_maximum_length():
    answer = parse_title("Visit: " + "A" * 100)

    assert answer == TitleAnswer(CorrectionKind.VISIT, "A" * 64)


def test_a_blank_title_has_no_answer():
    assert parse_title("   ") is None


def test_the_rendered_title_is_not_a_change_in_any_language():
    entry = visit(guests=[{"id": "g1", "name": "Alex"}], certainty=Certainty.CERTAIN)

    assert plan(entry, summary="Visit: Alex").answer is None
    assert plan(entry, summary=" besuch: alex ").answer is None


def test_an_edited_title_is_an_answer():
    entry = visit()

    assert plan(entry, summary="Delivery").answer == TitleAnswer(CorrectionKind.DELIVERY)


def test_unchanged_times_within_the_same_minute_are_no_change():
    entry = visit()

    result = plan(entry, start=entry.start.replace(microsecond=0, second=59), end=entry.end.replace(second=0))

    assert (result.start, result.end) == (None, None)
    assert not result.changed


def test_a_moved_start_or_end_is_a_change_to_the_exact_sent_time():
    entry = visit()

    result = plan(entry, start=at("11:45"), end=at("13:10"))

    assert (result.start, result.end) == (at("11:45"), at("13:10"))
    assert result.changed


def test_times_are_compared_with_the_effective_times_of_a_corrected_entry():
    entry = visit(
        correction=Correction(CorrectionKind.UNKNOWN, at("13:30"), "action", start=at("11:50"), end=at("13:20"))
    )

    result = plan(entry, start=at("11:50"), end=at("13:25"))

    assert (result.start, result.end) == (None, at("13:25"))


def test_the_end_of_an_open_entry_is_ignored():
    entry = visit(end=None)

    result = plan(entry, end=at("15:00"))

    assert result.end is None


def test_the_start_of_an_open_entry_can_change():
    entry = visit(end=None)

    result = plan(entry, start=at("11:30"), end=at("15:00"))

    assert result.start == at("11:30")


def test_added_description_lines_become_notes():
    entry = visit()

    result = plan(entry, sent="12:00 Front doorbell: ring\nWas the courier\n\n  Came with a box  ")

    assert result.notes == ["Was the courier", "Came with a box"]
    assert result.changed


def test_an_unchanged_or_shortened_or_missing_description_adds_nothing():
    entry = visit()

    assert plan(entry, sent="12:00 Front doorbell: ring").notes == []
    assert plan(entry, sent="").notes == []
    assert plan(entry, sent=None).notes == []
    assert not plan(entry, sent=None).changed


def test_line_breaks_and_spacing_of_the_browser_do_not_count_as_added_text():
    assert added_lines("a b\n\nc", "a  b\r\nc \r\n") == []


def test_a_changed_line_counts_as_added_text_and_the_old_line_is_not_restored():
    assert added_lines("12:00 ring\n12:01 door opened", "12:00 ring\n12:01 door slammed") == ["12:01 door slammed"]


def test_a_repeated_line_counts_once_per_generated_line():
    assert added_lines("ring\nring", "ring\nring\nring") == ["ring"]


def test_the_time_tolerance_is_one_minute_not_more():
    entry = visit()

    assert plan(entry, start=entry.start + timedelta(minutes=1)).start is not None
