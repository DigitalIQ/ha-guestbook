"""Turns an entry into a readable log and a title. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, tzinfo

from .effective import EffectiveKind, effective_guests, effective_kind
from .models import Certainty, Entry, Reason, Signal, SignalKind

DEFAULT_LANGUAGE = "en"
ACTION_SOURCE = "action"
RANGE_DASH = "\u2013"

TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "ring": "ring",
        "door_open": "opened",
        "door_close": "closed",
        "lock": "changed",
        "locked": "locked",
        "unlocked": "unlocked",
        "guest_home": "joined the network",
        "guest_away": "left the network",
        "resident": "resident signal",
        "action": "resident_unlock action",
        "from": "from",
        "until": "until",
        "start": "Started",
        "end": "Ended",
        "correction": "Correction",
        "notes": "Notes",
        "guest": "guest",
        "start_time": "start",
        "end_time": "end",
        "note": "note",
        "push": "push",
        "action_source": "action",
        "resident_kind": "resident",
        "delivery": "delivery",
        "visit": "visit",
        "unknown": "unknown",
        "title_visit": "Visit",
        "title_visit_uncertain": "Visit (uncertain)",
        "title_unanswered_ring": "Unanswered ring",
        "title_delivery": "Delivery",
        "title_resident_arrival": "Resident arrival",
        "ring_then_door": "ring followed by a door opening or presence",
        "ring_then_presence": "ring followed by presence",
        "guest_phone": "guest phone joined the network",
        "guest_phone_at_start": "guest phone was already on the network at startup",
        "manual": "added by hand",
        "resident_signal": "resident signal close to the ring",
        "ring_no_entry": "ring without a door opening or presence",
        "door_then_quiet": "door opening followed by a quiet period",
        "max_duration": "maximum duration reached",
        "guests_left": "all guest phones left",
        "corrected": "corrected by the user",
    },
    "de": {
        "ring": "geklingelt",
        "door_open": "geöffnet",
        "door_close": "geschlossen",
        "lock": "geändert",
        "locked": "abgeschlossen",
        "unlocked": "aufgeschlossen",
        "guest_home": "im Netzwerk angekommen",
        "guest_away": "Netzwerk verlassen",
        "resident": "Bewohnersignal",
        "action": "Aktion resident_unlock",
        "from": "ab",
        "until": "bis",
        "start": "Beginn",
        "end": "Ende",
        "correction": "Korrektur",
        "notes": "Notizen",
        "guest": "Gast",
        "start_time": "Beginn",
        "end_time": "Ende",
        "note": "Notiz",
        "push": "Push",
        "action_source": "Aktion",
        "resident_kind": "Bewohner",
        "delivery": "Lieferung",
        "visit": "Besuch",
        "unknown": "unklar",
        "title_visit": "Besuch",
        "title_visit_uncertain": "Besuch (unsicher)",
        "title_unanswered_ring": "Klingeln ohne Einlass",
        "title_delivery": "Lieferung",
        "title_resident_arrival": "Ankunft eines Bewohners",
        "ring_then_door": "Klingeln, danach Türöffnung oder Anwesenheit",
        "ring_then_presence": "Klingeln, danach Anwesenheit",
        "guest_phone": "Gästehandy im Netzwerk angekommen",
        "guest_phone_at_start": "Gästehandy war beim Start schon im Netzwerk",
        "manual": "von Hand hinzugefügt",
        "resident_signal": "Bewohnersignal nahe am Klingeln",
        "ring_no_entry": "Klingeln ohne Türöffnung oder Anwesenheit",
        "door_then_quiet": "Türöffnung, danach Ruhe",
        "max_duration": "Höchstdauer erreicht",
        "guests_left": "alle Gästehandys weg",
        "corrected": "vom Nutzer korrigiert",
    },
}


def _texts(language: str) -> dict[str, str]:
    return TEXTS.get(language.split("-")[0].split("_")[0].lower(), TEXTS[DEFAULT_LANGUAGE])


def render_title(entry: Entry, language: str) -> str:
    texts = _texts(language)
    kind = effective_kind(entry)
    if kind is EffectiveKind.UNANSWERED_RING:
        return texts["title_unanswered_ring"]
    if kind is EffectiveKind.RESIDENT_ARRIVAL:
        return texts["title_resident_arrival"]
    if kind is EffectiveKind.DELIVERY:
        return texts["title_delivery"]
    if guests := effective_guests(entry):
        return f"{texts['title_visit']}: " + ", ".join(guests)
    return texts["title_visit_uncertain"] if entry.certainty is Certainty.UNCERTAIN else texts["title_visit"]


def render_description(entry: Entry, language: str, names: Mapping[str, str], tz: tzinfo) -> str:
    texts = _texts(language)

    def clock(value: datetime) -> str:
        return value.astimezone(tz).strftime("%H:%M")

    def name(signal: Signal) -> str:
        if signal.source == ACTION_SOURCE:
            return texts["action"]
        return names.get(signal.source, signal.source)

    lines: list[tuple[datetime, str]] = []
    open_presence: dict[str, Signal] = {}
    for signal in sorted(entry.signals, key=lambda s: s.time):
        if signal.kind is SignalKind.PRESENCE_ON:
            open_presence.setdefault(signal.source, signal)
        elif signal.kind is SignalKind.PRESENCE_OFF:
            if (opened := open_presence.pop(signal.source, None)) is not None:
                lines.append((opened.time, f"{name(signal)} {clock(opened.time)}{RANGE_DASH}{clock(signal.time)}"))
            else:
                lines.append((signal.time, f"{name(signal)} {texts['until']} {clock(signal.time)}"))
        else:
            lines.append((signal.time, f"{clock(signal.time)} {name(signal)}: {_what(signal, texts)}"))
    for opened in open_presence.values():
        lines.append((opened.time, f"{name(opened)} {texts['from']} {clock(opened.time)}"))

    log = [line for _, line in sorted(lines, key=lambda item: item[0])]
    footer = _footer(entry, texts, clock, tz)
    return "\n".join([*log, "", *footer] if log and footer else [*log, *footer])


def _what(signal: Signal, texts: dict[str, str]) -> str:
    if signal.kind is SignalKind.LOCK:
        return texts.get(signal.state or "", signal.state or texts["lock"])
    if signal.kind is SignalKind.RESIDENT and signal.source == ACTION_SOURCE and signal.state:
        return f"{texts['resident']} ({signal.state})"
    return texts[signal.kind.value]


def _reason(reason: Reason, texts: dict[str, str]) -> str:
    return texts.get(reason.code) or reason.detail or reason.code


def _footer(entry: Entry, texts: dict[str, str], clock, tz: tzinfo) -> list[str]:
    footer = []
    if entry.reason:
        footer.append(f"{texts['start']}: {_reason(entry.reason, texts)}")
    if entry.end_reason:
        footer.append(f"{texts['end']}: {_reason(entry.end_reason, texts)}")
    if correction := entry.correction:
        source = texts["push"] if correction.source == "push" else texts["action_source"]
        label = texts["resident_kind"] if correction.kind == "resident" else texts.get(correction.kind, correction.kind)
        stamp = correction.time.astimezone(tz).strftime("%Y-%m-%d %H:%M")
        parts = [label]
        if correction.guest_name:
            parts.append(f"{texts['guest']} {correction.guest_name}")
        if correction.start:
            parts.append(f"{texts['start_time']} {clock(correction.start)}")
        if correction.end:
            parts.append(f"{texts['end_time']} {clock(correction.end)}")
        if correction.note:
            parts.append(f"{texts['note']}: {correction.note}")
        footer.append(f"{texts['correction']} ({source}, {stamp}): {', '.join(parts)}")
    if entry.notes:
        footer.append(f"{texts['notes']}:")
        footer.extend(f"- {note}" for note in entry.notes)
    return footer
