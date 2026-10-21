# Architecture

Contract for everyone building Guestbook. The spec says *what*; this file says *where* and *with which interfaces*. Change it when an interface changes.

## Layout

```
custom_components/guestbook/
  core/                 pure Python, no homeassistant imports
    __init__.py         re-exports the public names below
    models.py           Signal, SignalKind, Entry, EntryKind, Certainty, Reason, Correction, Guest, Settings, Change, ChangeKind
    engine.py           Engine (the rule core)
    render.py           description renderer (entry + language -> text)
  __init__.py           setup/unload, wires store, engine, adapter, timers, platforms
  const.py              DOMAIN, config keys, defaults, event names
  config_flow.py        config flow, options flow, guest subentry flow
  store.py              GuestbookStore (HA Store wrapper, purge)
  runtime.py            GuestbookRuntime: owns engine + store, applies Changes, fires events, notifies listeners
  adapter.py            state listeners -> Signal
  calendar.py           Visits and Rings calendars
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
    reason: Reason | None
    correction: Correction | None
    notes: list[str]
    settings: dict              # Settings snapshot at decision time
    rule_state: dict            # private engine bookkeeping, JSON-safe, survives restarts
    @property open -> bool      # end is None
    def to_dict() / from_dict()  # JSON-safe, ISO datetimes

class ChangeKind(StrEnum):
    OPENED, SIGNAL_ADDED, CLOSED, CLASSIFIED, CORRECTED

@dataclass(frozen=True)
class Change: kind: ChangeKind; entry: Entry; signal: Signal | None = None

class Engine:
    def __init__(self, settings: Settings, guests: list[Guest], entries: Iterable[Entry] = ()) -> None
        # entries: open/pending entries restored from the store
    def handle(self, signal: Signal) -> list[Change]
    def advance(self, now: datetime) -> list[Change]      # fire all deadlines <= now
    def next_deadline(self) -> datetime | None
    def active_entries(self) -> list[Entry]                # open visits and pending rings
    def set_settings(self, settings: Settings) -> None
    def set_guests(self, guests: list[Guest]) -> None
```

Change semantics (ticket 01): a ring opens a `PENDING_RING` entry (`OPENED`). Door or presence inside the ring window turns it into a `VISIT` (`CLASSIFIED`, with the triggering signal); further pending rings are merged into it and reported as `CLOSED`. A pending ring whose window ends is dropped (`CLOSED`, entry kind still `PENDING_RING`); the runtime removes such entries from the store. Ticket 04 replaces the drop with `CLASSIFIED` to `UNANSWERED_RING`. The ring window is half-open: a signal exactly at ring time + `ring_window` is too late. Ids are random UUID hex strings.

A `handle` call first runs `advance(signal.time)`, so deadlines before the signal fire first. Entries returned in Changes are the live objects; the runtime stores them.

## Home Assistant APIs

Config flow schemas use `probatio` (as in Home Assistant 2026.10 core), not `voluptuous`. Entity ids: the Visits calendar belongs to a "Guestbook" service device, so it is `calendar.guestbook_visits`. Signal time is `State.last_changed` of the new state.

## Runtime

`GuestbookRuntime` lives in `entry.runtime_data`. It owns the engine and the store, turns adapter signals into `engine.handle`, schedules one timer at `engine.next_deadline()`, saves changed entries, fires bus events, and calls registered listeners (`async_add_listener(cb) -> unsub`) so entities update. Corrections and additions go through runtime methods, not straight to the store.

## Storage

One `Store` key `guestbook.entries`, version 1: `{"entries": [Entry.to_dict(), ...]}`. Delayed save (a few seconds); flush on unload.

## Events

`guestbook_visit_started`, `guestbook_visit_event`, `guestbook_visit_ended`, `guestbook_visit_corrected` (names in `const.py`).

## Testing

- Core tests build signals with a helper `at("14:02")` on a fixed date.
- Integration tests set states with `hass.states.async_set`, move time with `async_fire_time_changed` and `freezer`, read calendars through `calendar.get_events` or the entity, and use `MockConfigEntry`.
- Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check custom_components tests`.
