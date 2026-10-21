import json
from datetime import timedelta

from custom_components.guestbook.core import Entry, EntryKind, entries_in_range, expired_entries, to_jsonl

from .helpers import at

RETENTION = timedelta(days=10)
NOW = at("12:00") + timedelta(days=20)


def entry(entry_id: str, start, end, kind: EntryKind = EntryKind.VISIT) -> Entry:
    return Entry(id=entry_id, kind=kind, start=start, end=end)


def test_closed_entries_older_than_the_retention_are_expired():
    old = entry("old", NOW - timedelta(days=11, hours=1), NOW - timedelta(days=11))
    recent = entry("recent", NOW - timedelta(days=9, hours=1), NOW - timedelta(days=9))

    assert expired_entries([old, recent], NOW, RETENTION) == [old]


def test_retention_is_measured_at_the_end_not_the_start():
    long_visit = entry("long", NOW - timedelta(days=12), NOW - timedelta(days=9))

    assert expired_entries([long_visit], NOW, RETENTION) == []


def test_an_entry_ending_exactly_at_the_cutoff_is_kept():
    edge = entry("edge", NOW - RETENTION - timedelta(hours=1), NOW - RETENTION)

    assert expired_entries([edge], NOW, RETENTION) == []


def test_open_entries_are_never_expired():
    open_visit = entry("open", NOW - timedelta(days=100), None)
    pending = entry("pending", NOW - timedelta(days=100), None, EntryKind.PENDING_RING)

    assert expired_entries([open_visit, pending], NOW, RETENTION) == []


def test_every_closed_kind_expires():
    kinds = (EntryKind.UNANSWERED_RING, EntryKind.RESIDENT_ARRIVAL, EntryKind.VISIT)
    old = [entry(kind.value, NOW - timedelta(days=50), NOW - timedelta(days=49), kind) for kind in kinds]

    assert expired_entries(old, NOW, RETENTION) == old


def test_range_filters_on_the_start_and_sorts_by_start():
    first = entry("first", at("10:00"), at("10:30"))
    second = entry("second", at("11:00"), None)
    third = entry("third", at("12:00"), at("12:30"))

    assert entries_in_range([third, first, second], None, None) == [first, second, third]
    assert entries_in_range([third, first, second], at("11:00"), at("12:00")) == [second]
    assert entries_in_range([third, first, second], at("10:30"), None) == [second, third]
    assert entries_in_range([third, first, second], None, at("11:00")) == [first]


def test_jsonl_has_one_entry_per_line():
    first = entry("first", at("10:00"), at("10:30"))
    second = entry("second", at("11:00"), None)

    lines = to_jsonl([first, second]).splitlines()

    assert [json.loads(line) for line in lines] == [
        {k: v for k, v in e.to_dict().items() if k not in ("rule_state", "question_token")} for e in (first, second)
    ]
    assert to_jsonl([]) == ""


def test_jsonl_leaves_out_the_private_rule_state():
    visit = entry("visit", at("10:00"), at("10:30"))
    visit.rule_state = {"deadline": "2026-10-21T10:05:00+00:00"}

    (line,) = to_jsonl([visit]).splitlines()

    assert "rule_state" not in json.loads(line)
    assert visit.rule_state == {"deadline": "2026-10-21T10:05:00+00:00"}
    assert "rule_state" in visit.to_dict()


def test_jsonl_leaves_out_the_one_time_question_token():
    visit = entry("visit", at("10:00"), at("10:30"))
    visit.question_token = "secret-token"

    (line,) = to_jsonl([visit]).splitlines()

    assert "question_token" not in json.loads(line)
    assert "secret-token" not in line
    assert visit.to_dict()["question_token"] == "secret-token"


def test_range_never_contains_pending_rings():
    pending = entry("pending", at("10:00"), None, EntryKind.PENDING_RING)
    visit = entry("visit", at("11:00"), None)

    assert entries_in_range([pending, visit], None, None) == [visit]
