"""Owns the engine and the store, schedules deadlines and tells listeners about changes."""

from __future__ import annotations

import itertools
import secrets
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.const import STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import ServiceValidationError
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_time_interval
from homeassistant.util import dt as dt_util

from .const import (
    DOMAIN,
    EVENT_VISIT_CORRECTED,
    EVENT_VISIT_ENDED,
    EVENT_VISIT_EVENT,
    EVENT_VISIT_STARTED,
    EXPORT_DIR,
    PURGE_INTERVAL,
    QUESTION_TOKEN_BYTES,
    SOURCE_ACTION,
    SOURCE_PUSH,
)
from .core import (
    Change,
    ChangeKind,
    Correction,
    CorrectionKind,
    EffectiveKind,
    Engine,
    Entry,
    EntryKind,
    Guest,
    Settings,
    Signal,
    clean_guest_name,
    effective_end,
    effective_guests,
    effective_kind,
    effective_start,
    entries_in_range,
    expired_entries,
    manual_visit,
    to_jsonl,
)
from .store import GuestbookStore


class GuestbookRuntime:
    def __init__(self, hass: HomeAssistant, store: GuestbookStore, engine: Engine, guests: list[Guest]) -> None:
        self._hass = hass
        self._guests = guests
        self._store = store
        self._engine = engine
        self._unsub_timer: CALLBACK_TYPE | None = None
        self._unsub_purge: CALLBACK_TYPE | None = None
        self._listeners: list[Callable[[], None]] = []
        self._change_listeners: list[Callable[[Change], None]] = []
        self._purge_listeners: list[Callable[[], None]] = []

    @callback
    def async_start(self) -> None:
        now = dt_util.utcnow()
        self.async_purge(now)
        self._apply(self._engine.advance(now))
        self._report_guests_away(now)
        self._announce_guests_at_home()
        self._unsub_purge = async_track_time_interval(self._hass, self.async_purge, PURGE_INTERVAL)

    async def async_stop(self) -> None:
        self._cancel_timer()
        if self._unsub_purge:
            self._unsub_purge()
            self._unsub_purge = None
        await self._store.async_flush()

    @property
    def settings(self) -> Settings:
        return self._engine.settings

    @callback
    def async_purge(self, now: datetime | None = None) -> int:
        """Delete the closed entries older than the retention; open entries stay. Returns how many went."""
        expired = expired_entries(self._store.entries, now or dt_util.utcnow(), self._engine.settings.retention)
        for entry in expired:
            self._store.async_remove(entry.id)
        if expired:
            self._notify()
            for listener in list(self._purge_listeners):
                listener()
        return len(expired)

    async def async_export(self, start: datetime | None = None, end: datetime | None = None) -> tuple[str, int]:
        """Write the entries with `start <= entry.start < end` as JSONL under the config directory."""
        entries = entries_in_range(self._store.entries, start, end)
        stem = f"guestbook-{dt_util.utcnow():%Y%m%dT%H%M%SZ}"
        path = await self._hass.async_add_executor_job(
            self._write, Path(self._hass.config.path(EXPORT_DIR)), stem, to_jsonl(entries)
        )
        return str(path), len(entries)

    @staticmethod
    def _write(directory: Path, stem: str, content: str) -> Path:
        """Write `<stem>.jsonl`; a file that exists already is never overwritten, the next free `-2`, `-3`, ... is used.

        The file is created exclusively, so two exports in the same second cannot pick the same name.
        """
        directory.mkdir(parents=True, exist_ok=True)
        for number in itertools.count(1):
            path = directory / (f"{stem}.jsonl" if number == 1 else f"{stem}-{number}.jsonl")
            try:
                with path.open("x", encoding="utf-8") as file:
                    file.write(content)
            except FileExistsError:
                continue
            return path
        raise AssertionError("unreachable")  # itertools.count never ends

    @callback
    def async_set_settings(self, settings: Settings) -> None:
        """Apply new rule numbers. Open visits keep running; their deadlines are derived from the new numbers."""
        self._engine.set_settings(settings)
        self._apply(self._engine.advance(dt_util.utcnow()))
        self._notify()

    @callback
    def async_add_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        self._listeners.append(listener)
        return lambda: self._listeners.remove(listener)

    @callback
    def async_add_change_listener(self, listener: Callable[[Change], None]) -> CALLBACK_TYPE:
        """Call `listener` with every Change the engine reports (the notifier uses this)."""
        self._change_listeners.append(listener)
        return lambda: self._change_listeners.remove(listener)

    @callback
    def async_add_purge_listener(self, listener: Callable[[], None]) -> CALLBACK_TYPE:
        """Call `listener` after a purge removed entries (repairs about purged visits go away)."""
        self._purge_listeners.append(listener)
        return lambda: self._purge_listeners.remove(listener)

    @callback
    def async_set_guests(self, guests: list[Guest]) -> None:
        self._guests = guests
        self._engine.set_guests(guests)
        self._apply(self._engine.advance(dt_util.utcnow()))
        self._announce_guests_at_home()
        self._notify()

    @callback
    def _report_guests_away(self, now: datetime) -> None:
        """Count phones that are away at startup as having left now; their restored visits then run out."""
        for guest in self._guests:
            for tracker in guest.trackers:
                state = self._hass.states.get(tracker)
                if state is not None and state.state not in (STATE_HOME, STATE_UNAVAILABLE, STATE_UNKNOWN):
                    self._apply(self._engine.guest_absent(guest.id, tracker, now))

    @callback
    def _announce_guests_at_home(self) -> None:
        """Report every guest phone that is already home: a visit starts or learns of the phone."""
        now = dt_util.utcnow()
        for guest in self._guests:
            for tracker in guest.trackers:
                if (state := self._hass.states.get(tracker)) is not None and state.state == STATE_HOME:
                    self._apply(self._engine.guest_present(guest.id, tracker, now))

    @callback
    def async_handle_signal(self, signal: Signal) -> None:
        self._apply(self._engine.handle(signal))

    @callback
    def async_entries(self, *kinds: EffectiveKind) -> list[Entry]:
        """Return the entries whose effective kind (correction over decision) is one of `kinds`."""
        return [entry for entry in self._store.entries if effective_kind(entry) in kinds]

    @callback
    def async_open_visits(self) -> list[Entry]:
        """Return the open visits, the most recent first."""
        visits = (entry for entry in self.async_entries(EffectiveKind.VISIT) if entry.open)
        return sorted(visits, key=lambda entry: entry.start, reverse=True)

    @callback
    def async_correct_entry(
        self,
        entry_id: str,
        kind: CorrectionKind,
        *,
        guest_name: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        note: str | None = None,
        source: str = SOURCE_ACTION,
    ) -> Entry:
        """Store a correction next to the decision; resident and delivery close an open visit."""
        entry = self._entry(entry_id)
        guest_name = (clean_guest_name(guest_name) or None) if guest_name is not None else None
        if entry.kind is EntryKind.PENDING_RING:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="entry_pending",
                translation_placeholders={"entry_id": entry_id},
            )
        self._check_times(start or entry.start, end or entry.end)
        now = dt_util.utcnow()
        entry.correction = Correction(kind, now, source, guest_name, start, end, note)
        self._store.async_put(entry)
        if kind in (CorrectionKind.RESIDENT, CorrectionKind.DELIVERY):
            self._apply(self._engine.close(entry.id, now))
        end_time = effective_end(entry)
        self._hass.bus.async_fire(
            EVENT_VISIT_CORRECTED,
            {
                "entry_id": entry.id,
                "kind": kind.value,
                "guest_name": guest_name,
                "guests": effective_guests(entry),
                "certainty": entry.certainty.value if entry.certainty else None,
                "start": effective_start(entry).isoformat(),
                "end": end_time.isoformat() if end_time else None,
            },
        )
        self._notify()
        return entry

    @callback
    def async_ask_question(self, entry: Entry) -> str:
        """Give the entry a fresh one-time token for its correction question and keep it in the storage."""
        entry.question_token = secrets.token_urlsafe(QUESTION_TOKEN_BYTES)
        self._store.async_put(entry)
        return entry.question_token

    @callback
    def async_answer_question(
        self, entry_id: str, token: str, kind: CorrectionKind, *, guest_name: str | None = None
    ) -> bool:
        """Save the answer to a correction question if `token` is the pending one of the entry.

        The token is used up by the answer. Returns False (and changes nothing) for an unknown entry or a wrong,
        missing or used token; a correction that is not possible raises like `async_correct_entry`.
        """
        entry = self.async_get_entry(entry_id)
        if (
            entry is None
            or not entry.question_token
            or not secrets.compare_digest(entry.question_token.encode(), token.encode())
        ):
            return False
        pending, entry.question_token = entry.question_token, None
        try:
            self.async_correct_entry(entry_id, kind, guest_name=guest_name, source=SOURCE_PUSH)
        except ServiceValidationError:
            entry.question_token = pending
            raise
        self._store.async_put(entry)
        return True

    @callback
    def async_add_visit(self, guests: list[str], start: datetime, end: datetime, note: str | None = None) -> Entry:
        """Log a visit the sensors missed. Names that match a guest profile (any case) use it."""
        self._check_times(start, end)
        entry = manual_visit(guests, self._guests, start, end, note, self._engine.settings)
        self._store.async_put(entry)
        self._notify()
        return entry

    @callback
    def async_add_note(self, entry_id: str, note: str) -> Entry:
        entry = self._entry(entry_id)
        entry.notes.append(note)
        self._store.async_put(entry)
        self._notify()
        return entry

    @callback
    def async_get_entry(self, entry_id: str) -> Entry | None:
        return next((entry for entry in self._store.entries if entry.id == entry_id), None)

    def _entry(self, entry_id: str) -> Entry:
        if (entry := self.async_get_entry(entry_id)) is not None:
            return entry
        raise ServiceValidationError(
            translation_domain=DOMAIN, translation_key="unknown_entry", translation_placeholders={"entry_id": entry_id}
        )

    @staticmethod
    def _check_times(start: datetime, end: datetime | None) -> None:
        if end is not None and end <= start:
            raise ServiceValidationError(translation_domain=DOMAIN, translation_key="end_before_start")

    @callback
    def _notify(self) -> None:
        for listener in list(self._listeners):
            listener()

    @callback
    def _apply(self, changes: list[Change]) -> None:
        for change in changes:
            if change.kind is ChangeKind.CLOSED and change.entry.kind is EntryKind.PENDING_RING:
                self._store.async_remove(change.entry.id)
            else:
                self._store.async_put(change.entry)
            self._fire_event(change)
            for listener in list(self._change_listeners):
                listener(change)
        self._schedule()
        if changes:
            self._notify()

    @callback
    def _fire_event(self, change: Change) -> None:
        entry = change.entry
        if change.previous is not None and change.previous.kind is EntryKind.VISIT and entry.end is not None:
            self._fire_ended(change.previous, entry.end, entry.kind.value)
            return
        if entry.kind is not EntryKind.VISIT:
            return
        data = self._event_data(entry)
        if change.kind in (ChangeKind.OPENED, ChangeKind.CLASSIFIED) and entry.open:
            self._hass.bus.async_fire(EVENT_VISIT_STARTED, {**data, "start": entry.start.isoformat()})
        elif change.kind is ChangeKind.SIGNAL_ADDED and change.signal is not None:
            signal = {"signal": change.signal.kind.value, "source": change.signal.source}
            self._hass.bus.async_fire(EVENT_VISIT_EVENT, {**data, **signal, "time": change.signal.time.isoformat()})
        elif change.kind is ChangeKind.CLOSED and entry.end is not None:
            self._fire_ended(entry, entry.end, entry.end_reason.code if entry.end_reason else "")

    @callback
    def _fire_ended(self, visit: Entry, end: datetime, reason: str) -> None:
        data = {
            **self._event_data(visit),
            "start": visit.start.isoformat(),
            "end": end.isoformat(),
            "duration": int((end - visit.start).total_seconds()),
            "reason": reason,
        }
        self._hass.bus.async_fire(EVENT_VISIT_ENDED, data)

    @staticmethod
    def _event_data(entry: Entry) -> dict[str, Any]:
        return {
            "entry_id": entry.id,
            "guests": [guest["name"] for guest in entry.guests],
            "certainty": entry.certainty.value if entry.certainty else None,
        }

    @callback
    def _schedule(self) -> None:
        self._cancel_timer()
        if (deadline := self._engine.next_deadline()) is not None:
            self._unsub_timer = async_track_point_in_utc_time(self._hass, self._async_deadline_reached, deadline)

    @callback
    def _cancel_timer(self) -> None:
        if self._unsub_timer:
            self._unsub_timer()
            self._unsub_timer = None

    @callback
    def _async_deadline_reached(self, now: datetime) -> None:
        self._unsub_timer = None
        self._apply(self._engine.advance(now))
