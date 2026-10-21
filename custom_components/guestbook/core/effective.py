"""What an entry counts as after the user's correction. The decision itself is never changed."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from .models import Entry


class EffectiveKind(StrEnum):
    PENDING_RING = "pending_ring"
    VISIT = "visit"
    UNANSWERED_RING = "unanswered_ring"
    RESIDENT_ARRIVAL = "resident_arrival"
    DELIVERY = "delivery"


CORRECTED_KINDS = {
    "resident": EffectiveKind.RESIDENT_ARRIVAL,
    "delivery": EffectiveKind.DELIVERY,
    "visit": EffectiveKind.VISIT,
}


def effective_kind(entry: Entry) -> EffectiveKind:
    """The kind that decides where the entry shows: the correction wins, `unknown` keeps the decision."""
    if entry.correction and (corrected := CORRECTED_KINDS.get(entry.correction.kind)):
        return corrected
    return EffectiveKind(entry.kind.value)


def effective_guests(entry: Entry) -> list[str]:
    """Guest names of the entry plus the name given in a visit correction."""
    names = [guest["name"] for guest in entry.guests]
    correction = entry.correction
    if correction is None or correction.kind != "visit" or not correction.guest_name:
        return names
    if correction.guest_name.casefold() not in {name.casefold() for name in names}:
        names.append(correction.guest_name)
    return names


def effective_start(entry: Entry) -> datetime:
    return entry.correction.start if entry.correction and entry.correction.start else entry.start


def effective_end(entry: Entry) -> datetime | None:
    return entry.correction.end if entry.correction and entry.correction.end else entry.end
