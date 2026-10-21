"""Entries that the user adds by hand."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from uuid import uuid4

from .models import Certainty, Entry, EntryKind, Guest, Reason, Settings, clean_guest_name, normalize_name

MANUAL = Reason("manual", "Added by hand")


def manual_visit(
    names: Iterable[str],
    profiles: Iterable[Guest],
    start: datetime,
    end: datetime,
    note: str | None,
    settings: Settings,
) -> Entry:
    """A closed, certain visit. Names that match a guest profile (any case) use it; others are free names.

    Names are trimmed and cut to the maximum length. A name given twice counts once. Blank names are dropped.
    """
    by_name = {normalize_name(guest.name): guest for guest in profiles}
    members: dict[str, dict[str, str]] = {}
    for name in (clean_guest_name(n) for n in names if n.strip()):
        profile = by_name.get(normalize_name(name))
        members.setdefault(
            normalize_name(name), {"id": profile.id, "name": profile.name} if profile else {"id": "", "name": name}
        )
    return Entry(
        id=uuid4().hex,
        kind=EntryKind.VISIT,
        start=start,
        end=end,
        certainty=Certainty.CERTAIN,
        guests=list(members.values()),
        reason=MANUAL,
        notes=[note] if note else [],
        settings=settings.to_dict(),
    )
