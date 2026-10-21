# Architecture

Contract for everyone building Guestbook. The spec says *what*; this file says *where* and *with which interfaces*. Change it when an interface changes.

## Layout

```
custom_components/guestbook/
  core/                 pure Python, no homeassistant imports
    __init__.py         re-exports the public names below
    models.py           Signal, SignalKind, Entry, EntryKind, Certainty, Reason, Correction, Guest, Settings, Change, ChangeKind
    engine.py           Engine (the rule core)
    render.py           renderer: render_description, render_title (entry + language -> text)
  __init__.py           setup/unload, wires store, engine, adapter, timers, platforms
  const.py              DOMAIN, config keys, defaults, event names
  config_flow.py        config flow, options flow, guest subentry flow
  store.py              GuestbookStore (HA Store wrapper, purge)
  runtime.py            GuestbookRuntime: owns engine + store, applies Changes, fires events, notifies listeners
  adapter.py            state listeners -> Signal (doorbells, doors, presence, locks, resident signals)
  calendar.py           Visits and Rings calendars (shared base class; Visits shows kind visit, Rings shows kind unanswered_ring)
  sensor.py / binary_sensor.py
  services.py           actions
  notifier.py           pushes and correction answers
  repairs.py            repair issues and fix flows
  services.yaml, strings.json, translations/{en,de}.json, manifest.json, brand/
tests/
  core/                 seam 1: rule core, no hass fixture
  integration/          seam 2: pytest-homeassistant-custom-component
```

## Rule core interface (`core`)

All datetimes are timezone-aware UTC. The core never reads the clock.

```python
class SignalKind(StrEnum):
    RING, DOOR_OPEN, DOOR_CLOSE, PRESENCE_ON, PRESENCE_OFF, LOCK, GUEST_HOME, GUEST_AWAY, RESIDENT

@dataclass(frozen=True)
class Signal:
    kind: SignalKind
    time: datetime
    source: str            # entity id, or "action" for resident_unlock
    state: str | None = None
    guest_id: str | None = None   # for GUEST_HOME / GUEST_AWAY

class EntryKind(StrEnum):
    PENDING_RING, VISIT, UNANSWERED_RING, RESIDENT_ARRIVAL

class Certainty(StrEnum):
    CERTAIN, UNCERTAIN

@dataclass
class Reason: code: str; detail: str = ""

@dataclass
class Correction:
    kind: str              # resident | delivery | visit | unknown
    time: datetime
    source: str            # push | action
    guest_name: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    note: str | None = None

@dataclass
class Guest: id: str; name: str; trackers: list[str]

@dataclass
class Settings:
    ring_window: timedelta = 5 min
    resident_window: timedelta = 3 min
    quiet_period: timedelta = 10 min
    entry_grace: timedelta = 2 min     # door openings this soon after start do not end a visit
    phone_grace: timedelta = 5 min
    max_duration: timedelta = 4 h
    retention: timedelta = 365 days
    def to_dict() / from_dict()

@dataclass
class Entry:
    id: str; kind: EntryKind; start: datetime; end: datetime | None
    certainty: Certainty | None
    guests: list[dict]          # [{"id": ..., "name": ...}]
    signals: list[Signal]
    reason: Reason | None       # why the entry got its kind (start decision)
    end_reason: Reason | None   # why a visit ended: door_then_quiet | max_duration
    correction: Correction | None
    notes: list[str]
    settings: dict              # Settings snapshot at decision time
    rule_state: dict            # private engine bookkeeping, JSON-safe, survives restarts
    @property open -> bool      # end is None
    def to_dict() / from_dict()  # JSON-safe, ISO datetimes

class ChangeKind(StrEnum):
    OPENED, SIGNAL_ADDED, CLOSED, CLASSIFIED, CORRECTED

@dataclass(frozen=True)
class Change: kind: ChangeKind; entry: Entry; signal: Signal | None = None; previous: Entry | None = None
    # previous: shallow copy of the entry before a reclassification (resident arrival), else None

class Engine:
    def __init__(self, settings: Settings, guests: list[Guest], entries: Iterable[Entry] = ()) -> None
        # entries: open/pending entries restored from the store
    def handle(self, signal: Signal) -> list[Change]
    def guest_present(self, guest_id: str, tracker: str, now: datetime) -> list[Change]
    def advance(self, now: datetime) -> list[Change]      # fire all deadlines <= now
    def next_deadline(self) -> datetime | None
    def active_entries(self) -> list[Entry]                # open visits and pending rings
    def set_settings(self, settings: Settings) -> None
    def set_guests(self, guests: list[Guest]) -> None
```

Change semantics (ticket 01): a ring opens a `PENDING_RING` entry (`OPENED`). Door or presence inside the ring window turns it into a `VISIT` (`CLASSIFIED`, with the triggering signal); further pending rings are merged into it and reported as `CLOSED`. A pending ring whose window ends with nothing is classified (`CLASSIFIED`, ticket 04): `kind` `UNANSWERED_RING`, `reason` `ring_no_entry`, `end` = ring time + 1 minute (a short calendar event), `certainty` None; the entry is closed and leaves `active_entries()`. Pending rings that are merged into a visit are reported as `CLOSED` with the kind still `PENDING_RING`; the runtime removes those from the store (no other entry is ever dropped). The ring window is half-open: a signal exactly at ring time + `ring_window` is too late. Ids are random UUID hex strings.

Visit end (ticket 02): an open uncertain visit has two deadlines and `next_deadline` returns the earliest of all active entries. The end candidate is the last `DOOR_OPEN` signal at or after `entry_grace` past the signal that made the ring a visit (the guest coming in); it ends the visit once `quiet_period` passes without a further door opening (`CLOSED`, `end` = that door opening, `end_reason` `door_then_quiet`). Otherwise the visit ends at `start + max_duration` (`end_reason` `max_duration`); the maximum wins when the quiet deadline would fall after it. Both half-open: a door opening exactly at the quiet deadline is too late. Deadlines are derived from the entry's signals and the current settings, so an open visit restored from the store needs no extra bookkeeping. While a visit is open, `DOOR_OPEN`, `DOOR_CLOSE`, `PRESENCE_ON`, `PRESENCE_OFF` and `LOCK` signals are appended to it (`SIGNAL_ADDED`); a door opening or presence that turns a pending ring into a visit is consumed by that visit and not appended to other open visits.

A `handle` call first runs `advance(signal.time)`, so deadlines before the signal fire first. Entries returned in Changes are the live objects; the runtime stores them.

Resident signals (ticket 03): the engine keeps resident signals of the last `resident_window` in memory only. They are not stored; a restart inside that window forgets them (accepted, the window is minutes). A `RING` with a resident signal in `[ring - resident_window, ring]` becomes a `RESIDENT_ARRIVAL` at once (one `CLASSIFIED` change, no `OPENED`): `reason` `resident_signal`, `start` = `end` = ring time, `signals` = the resident signals plus the ring, `certainty` None. A `RESIDENT` signal turns every pending ring into a `RESIDENT_ARRIVAL` (`end` = signal time) and every open uncertain visit with a ring inside its ring window (`ring <= signal < ring + ring_window`) as well; `end_reason` is cleared. A `CLASSIFIED` change whose entry has an `end` is final: the entry left `active_entries()`. Resident signals outside these cases change nothing and are not appended to visits.

Guest phones (ticket 05): `GUEST_HOME` / `GUEST_AWAY` signals carry `source` = the tracker entity id and `guest_id`; a signal for an unknown guest is ignored. `GUEST_HOME` with no open visit opens a certain `VISIT` (`OPENED`, `reason` `guest_phone`, one guest). With an open visit the guest joins it (`SIGNAL_ADDED`): an open certain visit is preferred, an open uncertain one becomes `CERTAIN` and keeps its start decision (`reason`). A guest already in an open visit only gets the signal appended. `GUEST_AWAY` is appended to every open visit that contains the guest. A certain visit has no max duration and ignores door quiet periods: it is open while the last signal of any known tracker is `GUEST_HOME`. Once every tracker is away its deadline is the latest away time plus `phone_grace`, and it ends there (`CLOSED`, `end` = that away time, `end_reason` `guests_left`). A phone back before the deadline cancels it; at the deadline it is too late (half-open), the old visit closes and a new one opens. Trackers no longer listed in the guests count as away, so `set_guests` can make a visit due; the caller advances afterwards. A ring plus door or presence while a certain visit is open does not open an uncertain visit: the pending rings are reported as `CLOSED` and the door or presence signal is appended to the certain visit (`SIGNAL_ADDED`). A resident signal never turns a certain visit into a resident arrival.

Guest already home (lifecycle fix): `guest_present(guest_id, tracker, now)` is for a phone that is `home` at startup or when its guest is added, without a state change. It does nothing for an unknown guest or when an open visit already has the guest (restored visits are not duplicated). Otherwise it behaves like `GUEST_HOME` at `now` (joins an open visit), but a visit it opens has `reason` `guest_phone_at_start`. The runtime calls it for every guest with a `home` tracker in `async_start` and `async_set_guests`.

## Renderer (ticket 07)

`core/render.py`, pure functions, texts in `de` and `en` (a region suffix is ignored, other languages fall back to `en`).

- `render_description(entry, language, names, tz) -> str`: `names` maps entity id to friendly name (missing ids show the entity id), `tz` is a `tzinfo`. One line per signal in time order, `HH:MM <name>: <what>` in local time. The source `action` reads "resident_unlock action". Presence on/off of one sensor is condensed to `<name> HH:MM–HH:MM` (placed at the on time); a stretch still on reads `<name> from HH:MM`, an off without an on in the entry reads `<name> until HH:MM`. No length limit. After a blank line: start reason, end reason, the correction (with kind, guest, start, end, note) and the notes; reason codes are translated, unknown codes show the reason detail.
- `render_title(entry, language)`: `Visit: Alex, Sam`, `Visit (uncertain)`, `Visit`, `Unanswered ring` and the German counterparts.
- The calendars call both with `hass.config.language`, the default time zone and the friendly names of the signal sources (`State.name`).

## Home Assistant APIs

Config flow schemas use `probatio` (as in Home Assistant 2026.10 core), not `voluptuous`. Entity ids: the Visits calendar belongs to a "Guestbook" service device, so it is `calendar.guestbook_visits`; the Rings calendar is `calendar.guestbook_rings`. Resident arrivals appear in no calendar. Signal time is `State.last_changed` of the new state. Changes from or to `unavailable`/`unknown` are ignored, except `unknown` to a timestamp on `event` entities. Resident signal entities fire on a change to `on`, `home` or `unlocked` or on a new `event` timestamp; lock entities (`locks` source, lock domain) emit a `LOCK` signal with the new state on every state change.

Action `guestbook.resident_unlock` (optional `source` text) is registered in `async_setup` (`services.py`). It hands `Signal(RESIDENT, now, "action", state=source)` to every loaded entry's runtime and raises `ServiceValidationError` (`not_loaded`) when no entry is loaded.

Guests (ticket 05): config subentries of type `guest` (`SUBENTRY_GUEST`) with data `name` and `trackers` (list of `device_tracker` entity ids, may be empty). The subentry id is the guest id. `GuestSubentryFlow` in `config_flow.py` has the steps `user` and `reconfigure`. The entry update listener (set up in `async_setup_entry`) rebuilds the guest list on every entry update and calls `SignalAdapter.async_set_guests` (re-subscribes the tracker listeners) and `GuestbookRuntime.async_set_guests` (engine, advance, listeners). No reload, so open visits survive guest changes. The adapter turns a tracker state change into `GUEST_HOME` (new state `home`) or `GUEST_AWAY` (old state `home`, new state anything else); changes from or to `unavailable`/`unknown` are ignored. `SignalAdapter(hass, config, guests, on_signal)`. The Visits calendar entity (`event`) reports an open visit with an end one minute after now so the entity state is `on`; `async_get_events` keeps the end at now. The title is `Visit: <names>` when guests are known, otherwise `Visit (uncertain)`.

Sensors (ticket 06): `entity.py` holds `GuestbookEntity` (has_entity_name, no polling, registers a runtime listener, device = the "Guestbook" service device unless a device is passed); calendars and sensors derive from it. `binary_sensor.guestbook_visit_active` is on while `runtime.async_open_visits()` is not empty. `sensor.guestbook_current_visit` shows the most recent open visit: state = comma-joined guest names, `unknown` text for a visit without guests, `None` (HA shows unknown) when no visit is open; attributes `entry_id`, `start` (ISO), `certainty` only while a visit is open. One `GuestSensor` per guest subentry (`binary_sensor.<guest>_visiting`), added with `config_subentry_id`, on while the guest is in an open visit. HA requires a device to belong to one subentry, so each guest gets its own service device (identifier `(DOMAIN, subentry_id)`, name = guest name). The binary sensor platform has its own entry update listener that adds sensors for new guests and renames the device of renamed ones; `async_remove_subentry` removes the entities and the device. All translation keys live under `entity.binary_sensor` (`visit_active`, `guest`) and `entity.sensor` (`current_visit`).

## Runtime

`GuestbookRuntime` lives in `entry.runtime_data`. It owns the engine and the store, turns adapter signals into `engine.handle`, schedules one timer at `engine.next_deadline()`, saves changed entries, fires bus events, and calls registered listeners (`async_add_listener(cb) -> unsub`) so entities update. `async_open_visits()` returns the open visits, most recent first. Corrections and additions go through runtime methods, not straight to the store.

## Storage

One `Store` key `guestbook.entries`, version 1: `{"entries": [Entry.to_dict(), ...]}`. Delayed save (a few seconds); flush on unload.

## Events

`guestbook_visit_started`, `guestbook_visit_event`, `guestbook_visit_ended`, `guestbook_visit_corrected` (names in `const.py`).

The runtime fires them from the Changes of entries of kind `VISIT` (ticket 08). Payload values are JSON-safe; guests are names, times are ISO strings (UTC).

- `guestbook_visit_started`: `OPENED` or `CLASSIFIED` change of an open visit. `entry_id`, `guests`, `certainty`, `start`.
- `guestbook_visit_event`: `SIGNAL_ADDED` change of a visit. `entry_id`, `guests`, `certainty`, `signal` (SignalKind value), `source` (entity id), `time`. The signal that turns a ring into a visit is part of `started` and not repeated. A guest phone joining an open visit is a `guest_home` event.
- `guestbook_visit_ended`: `CLOSED` change of a visit. `entry_id`, `guests`, `certainty`, `start`, `end`, `duration` (whole seconds), `reason` (the end reason code: `door_then_quiet`, `max_duration`, `guests_left`). A visit that already fired `started` and is then reclassified as a resident arrival fires `ended` too, with `reason` `resident_arrival` and the data of the visit as it was (certainty `uncertain`).
- Resident arrivals and unanswered rings that never fired `started` fire nothing.

## Testing

- Core tests build signals with a helper `at("14:02")` on a fixed date.
- Integration tests set states with `hass.states.async_set`, move time with `async_fire_time_changed` and `freezer`, read calendars through `calendar.get_events` or the entity, and use `MockConfigEntry`.
- Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check custom_components tests`.
