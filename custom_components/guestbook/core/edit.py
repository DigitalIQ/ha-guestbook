"""What an edit in a calendar dialog means for an entry. Pure Python, no Home Assistant imports.

The dialog sends a title, a start, an end and a description. The title is read like an answer to the correction
question, the times become display overrides and added description text becomes notes. Nothing is stored here.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime

from .effective import effective_end, effective_start
from .models import CorrectionKind, Entry, clean_guest_name
from .render import TEXTS, render_title

VISIT_PREFIX = re.compile(r"^(?:visit|besuch)\s*:\s*(.*)$", re.IGNORECASE)


def _words(text: str) -> str:
    """The form in which titles are compared: trimmed, case-insensitive, one space between words, plain apostrophe."""
    return " ".join(text.replace("\u2019", "'").casefold().split())


KEYWORDS: dict[CorrectionKind, tuple[str, ...]] = {
    CorrectionKind.RESIDENT: (
        "that was me",
        "was me",
        "me",
        "resident",
        "resident arrival",
        "war ich",
        "das war ich",
        "ich",
        "bewohner",
        "ankunft eines bewohners",
    ),
    CorrectionKind.DELIVERY: ("delivery", "parcel", "lieferung", "paket"),
    CorrectionKind.UNKNOWN: (
        "don't know",
        "do not know",
        "dont know",
        "unknown",
        "unsure",
        "visit (uncertain)",
        "unanswered ring",
        "weiß nicht",
        "weiss nicht",
        "unklar",
        "unsicher",
        "besuch (unsicher)",
        "klingeln ohne einlass",
    ),
    CorrectionKind.VISIT: ("visit", "besuch"),
}
KIND_OF_WORDS = {_words(word): kind for kind, words in KEYWORDS.items() for word in words}


@dataclass(frozen=True)
class TitleAnswer:
    """The correction a title stands for."""

    kind: CorrectionKind
    guest_name: str | None = None


@dataclass(frozen=True)
class EditPlan:
    """What an edit changes. `None` and empty mean "leave as it is"."""

    answer: TitleAnswer | None = None
    start: datetime | None = None
    end: datetime | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return bool(self.answer or self.start or self.end or self.notes)


def parse_title(text: str) -> TitleAnswer | None:
    """Read a title like an answer: a known word in English or German, `Visit: <name>`, or a bare name.

    Returns None for a blank title.
    """
    if not (text := text.strip()):
        return None
    if (kind := KIND_OF_WORDS.get(_words(text))) is not None:
        return TitleAnswer(kind)
    if (prefixed := VISIT_PREFIX.match(text)) is not None:
        return TitleAnswer(CorrectionKind.VISIT, clean_guest_name(prefixed.group(1)) or None)
    return TitleAnswer(CorrectionKind.VISIT, clean_guest_name(text))


def added_lines(generated: str, sent: str | None) -> list[str]:
    """The lines of `sent` that the generated log does not have: what the user typed into the description.

    Lines are compared without line break style, outer spaces and repeated inner spaces. A line that the user
    removed is ignored (the log is generated), a line that the user changed counts as a new line.
    """
    remaining = Counter(_line(line) for line in generated.splitlines() if line.strip())
    added = []
    for line in (raw.strip() for raw in (sent or "").splitlines() if raw.strip()):
        if remaining[key := _line(line)] > 0:
            remaining[key] -= 1
        else:
            added.append(line)
    return added


def _line(text: str) -> str:
    return " ".join(text.split())


def _same_minute(a: datetime, b: datetime) -> bool:
    """The dialog works with whole minutes (and drops microseconds), so a time in the same minute is unchanged."""
    return a.replace(second=0, microsecond=0) == b.replace(second=0, microsecond=0)


def plan_edit(
    entry: Entry, *, summary: str, start: datetime, end: datetime, generated: str, sent: str | None
) -> EditPlan:
    """Compare what the dialog sent with what it showed and return only the differences.

    `generated` is the description the calendar showed, `sent` the one that came back. The end of an open entry is
    ignored: the calendar shows "now" as its end, and the dialog cannot tell that from an end the user typed.
    """
    titles = {_words(render_title(entry, language)) for language in TEXTS}
    answer = None if _words(summary) in titles else parse_title(summary)
    return EditPlan(
        answer=answer,
        start=None if _same_minute(start, effective_start(entry)) else start,
        end=None if entry.open or _same_minute(end, effective_end(entry) or end) else end,
        notes=added_lines(generated, sent),
    )
