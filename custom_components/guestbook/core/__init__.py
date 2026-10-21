"""Rule core: turns signals into entries. No Home Assistant imports."""

from .archive import entries_in_range, expired_entries, to_jsonl
from .effective import EffectiveKind, effective_end, effective_guests, effective_kind, effective_start
from .engine import Engine
from .messages import PushKind, action_id, correction_actions, parse_action_id, push_message, push_title, unknown_guest
from .models import (
    Certainty,
    Change,
    ChangeKind,
    Correction,
    Entry,
    EntryKind,
    Guest,
    Reason,
    Settings,
    Signal,
    SignalKind,
)
from .render import render_description, render_title

__all__ = [
    "Certainty",
    "Change",
    "ChangeKind",
    "Correction",
    "EffectiveKind",
    "Engine",
    "Entry",
    "EntryKind",
    "Guest",
    "PushKind",
    "Reason",
    "Settings",
    "Signal",
    "SignalKind",
    "action_id",
    "correction_actions",
    "effective_end",
    "effective_guests",
    "effective_kind",
    "effective_start",
    "entries_in_range",
    "expired_entries",
    "parse_action_id",
    "push_message",
    "push_title",
    "render_description",
    "render_title",
    "to_jsonl",
    "unknown_guest",
]
