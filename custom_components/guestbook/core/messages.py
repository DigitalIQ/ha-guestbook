"""Texts and button definitions of the pushes. Pure Python, no Home Assistant imports."""

from __future__ import annotations

from enum import StrEnum

DEFAULT_LANGUAGE = "en"
ACTION_PREFIX = "GUESTBOOK_"
CORRECTION_KINDS = ("resident", "delivery", "visit", "unknown")
ANDROID_ACTION_LIMIT = 3


class PushKind(StrEnum):
    ARRIVAL = "arrival"
    END = "end"
    UNANSWERED_RING = "unanswered_ring"
    CORRECTION = "correction"


TEXTS: dict[str, dict[str, str]] = {
    "en": {
        "title_arrival": "Visit",
        "title_end": "Visit ended",
        "title_unanswered_ring": "Unanswered ring",
        "title_correction": "Who was that?",
        "arrival": "Arrived: {names}.",
        "arrival_unknown": "Someone arrived.",
        "end": "Left: {names}.",
        "end_unknown": "The visit is over.",
        "unanswered_ring": "Someone rang. No door opening or presence followed.",
        "correction": "Someone rang and came in. Was that you, a delivery or a visit?",
        "entry_id": "Entry id: {entry_id}",
        "correction_hint": "Answer with the action guestbook.correct_entry.",
        "resident": "That was me",
        "delivery": "Delivery",
        "visit": "Visit",
        "unknown": "Don't know",
        "save": "Save",
        "placeholder": "Name of the guest",
        "unknown_guest": "Unknown guest",
    },
    "de": {
        "title_arrival": "Besuch",
        "title_end": "Besuch beendet",
        "title_unanswered_ring": "Klingel ohne Antwort",
        "title_correction": "Wer war das?",
        "arrival": "Angekommen: {names}.",
        "arrival_unknown": "Jemand ist angekommen.",
        "end": "Gegangen: {names}.",
        "end_unknown": "Der Besuch ist vorbei.",
        "unanswered_ring": "Jemand hat geklingelt. Danach kam keine Türöffnung und keine Anwesenheit.",
        "correction": "Jemand hat geklingelt und ist hereingekommen. Warst du das, eine Lieferung oder ein Besuch?",
        "entry_id": "Eintrags-ID: {entry_id}",
        "correction_hint": "Antworte mit der Aktion guestbook.correct_entry.",
        "resident": "War ich",
        "delivery": "Lieferung",
        "visit": "Besuch",
        "unknown": "Weiß nicht",
        "save": "Speichern",
        "placeholder": "Name des Gastes",
        "unknown_guest": "Unbekannter Gast",
    },
}


def _texts(language: str) -> dict[str, str]:
    return TEXTS.get(language.split("-")[0].split("_")[0].lower(), TEXTS[DEFAULT_LANGUAGE])


def unknown_guest(language: str) -> str:
    """The word for a visit without known guests."""
    return _texts(language)["unknown_guest"]


def push_title(kind: PushKind, language: str) -> str:
    return _texts(language)[f"title_{kind.value}"]


def push_message(kind: PushKind, language: str, guests: list[str], entry_id: str | None = None) -> str:
    """Return the text of a push; with an `entry_id` (text-only targets) the id is appended."""
    texts = _texts(language)
    if kind is PushKind.UNANSWERED_RING or kind is PushKind.CORRECTION:
        parts = [texts[kind.value]]
    elif guests:
        parts = [texts[kind.value].format(names=", ".join(guests))]
    else:
        parts = [texts[f"{kind.value}_unknown"]]
    if entry_id is not None:
        parts.append(texts["entry_id"].format(entry_id=entry_id))
        if kind is PushKind.CORRECTION:
            parts.append(texts["correction_hint"])
    return " ".join(parts)


def action_id(kind: str, entry_id: str) -> str:
    return f"{ACTION_PREFIX}{kind.upper()}_{entry_id}"


def parse_action_id(action: str) -> tuple[str, str] | None:
    """Return (correction kind, entry id) of an action id built by `action_id`, else None."""
    if not action.startswith(ACTION_PREFIX):
        return None
    kind, _, entry_id = action.removeprefix(ACTION_PREFIX).partition("_")
    if kind.lower() not in CORRECTION_KINDS or kind != kind.upper() or not entry_id:
        return None
    return kind.lower(), entry_id


def correction_actions(language: str, entry_id: str, *, android: bool = False) -> list[dict[str, str]]:
    """Return the buttons of the correction question; Android shows three at most."""
    texts = _texts(language)
    actions = []
    for kind in CORRECTION_KINDS:
        action = {"action": action_id(kind, entry_id), "title": texts[kind]}
        if kind == "visit":
            action |= {
                "behavior": "textInput",
                "textInputButtonTitle": texts["save"],
                "textInputPlaceholder": texts["placeholder"],
            }
        actions.append(action)
    return actions[:ANDROID_ACTION_LIMIT] if android else actions
