# Architecture

Contract for everyone building Guestbook. The spec says *what*; this file says *where* and *with which interfaces*. Change it when an interface changes.

## Layout

```
custom_components/guestbook/
  core/                 pure Python, no homeassistant imports
    __init__.py         re-exports the public names below
    models.py           Signal, SignalKind, Entry, EntryKind, Certainty, Reason, Correction, CorrectionKind, Guest, Settings, Change, ChangeKind, normalize_name
    engine.py           Engine (the rule core)
    manual.py           manual_visit (the entry for add_visit)
    effective.py        EffectiveKind, effective_kind/guests/start/end (entry + correction)
    latest.py           latest_entry (the entry that buttons and an omitted entry_id mean)
    render.py           renderer: render_description, render_title (entry + language -> text)
    archive.py          expired_entries, entries_in_range, to_jsonl (retention purge and export selection)
    messages.py         push texts and buttons: PushKind, unknown_guest, push_title, push_message, correction_actions, action_id, parse_action_id
  __init__.py           setup/unload, wires store, engine, adapter, timers, platforms
  const.py              DOMAIN, config keys, defaults, event names
  config_flow.py        config flow, options flow, guest subentry flow
  guests.py             guests_of(entry): Guest list from the guest subentries
  settings.py           entry options (minutes, hours, days) <-> core Settings
  store.py              GuestbookStore (HA Store wrapper, purge)
  runtime.py            GuestbookRuntime: owns engine + store, applies Changes, fires events, notifies listeners
  adapter.py            state listeners -> Signal (doorbells, doors, presence, locks, resident signals)
  calendar.py           Visits and Rings calendars (shared base class; Visits shows effective kind visit, Rings shows effective kinds unanswered_ring and delivery)
  sensor.py / binary_sensor.py / button.py / text.py
  services.py           actions
  notifier.py           Notifier: pushes and correction answers (ticket 10, 11)
  repairs.py            repair issues (missing sources, guest suggestions) and fix flows
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

class CorrectionKind(StrEnum):
    RESIDENT, DELIVERY, VISIT, UNKNOWN     # values "resident", "delivery", "visit", "unknown" (JSON, action field, button ids)

def normalize_name(name: str) -> str       # strip + casefold; the only way guest names are compared
def clean_guest_name(name: str) -> str     # strip + cut to MAX_GUEST_NAME (64); every input that becomes a guest name goes through it

@dataclass
class Correction:
    kind: CorrectionKind
    time: datetime
    source: str            # push | action | button
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
    question_token: str | None  # one-time token of the pending correction question (stored, never exported)
    dropped_signals: int        # ordinary signals dropped by the signal cap (stored and exported)
    @property present_guest_ids -> set[str]   # guests of the entry who are still there (see Guest phones)
    @property open -> bool      # end is None
    def to_dict() / from_dict()  # JSON-safe, ISO datetimes

class ChangeKind(StrEnum):
    OPENED, SIGNAL_ADDED, CLOSED, CLASSIFIED, CORRECTED, GUEST_LEFT

@dataclass(frozen=True)
class Change: kind: ChangeKind; entry: Entry; signal: Signal | None = None; previous: Entry | None = None
    # previous: shallow copy of the entry before a reclassification (resident arrival), else None

class Engine:
    def __init__(self, settings: Settings, guests: list[Guest], entries: Iterable[Entry] = ()) -> None
        # entries: open/pending entries restored from the store
    def handle(self, signal: Signal) -> list[Change]
    def guest_present(self, guest_id: str, tracker: str, now: datetime) -> list[Change]
    def guest_absent(self, guest_id: str, tracker: str, now: datetime) -> list[Change]
    def advance(self, now: datetime) -> list[Change]      # fire all deadlines <= now
    def next_deadline(self) -> datetime | None
    def close(self, entry_id: str, now: datetime) -> list[Change]   # ticket 09, see Corrections
    settings: Settings (read-only property)
    def active_entries(self) -> list[Entry]                # open visits and pending rings
    def set_settings(self, settings: Settings) -> None
    def set_guests(self, guests: list[Guest]) -> None
```

Change semantics (ticket 01): a ring opens a `PENDING_RING` entry (`OPENED`). Door or presence inside the ring window turns it into a `VISIT` (`CLASSIFIED`, with the triggering signal); further pending rings are merged into it and reported as `CLOSED`. A pending ring whose window ends with nothing is classified (`CLASSIFIED`, ticket 04): `kind` `UNANSWERED_RING`, `reason` `ring_no_entry`, `end` = ring time + 1 minute (a short calendar event), `certainty` None; the entry is closed and leaves `active_entries()`. Pending rings that are merged into a visit are reported as `CLOSED` with the kind still `PENDING_RING`; the runtime removes those from the store (no other entry is ever dropped). The ring window end is inclusive for the signals that make a visit: a door opening or presence exactly at ring time + `ring_window` still counts (`handle` does not expire a pending ring whose deadline equals the signal time for these signals). `advance(now)` expires a ring only once `now` is past the end of its window, so a clock that reaches the end first does not cost the door opening at that instant; the timer is scheduled by `next_deadline()`, which for a pending ring returns the end of the window plus one second (`RING_WAKE_UP_DELAY`) so that signals stamped at the end have arrived. A resident signal, a ring or a phone signal exactly at the end is too late (`handle` expires the ring first for those). Ids are random UUID hex strings.

Visit end (ticket 02): an open uncertain visit has two deadlines and `next_deadline` returns the earliest of all active entries. The end candidate is the last `DOOR_OPEN` signal at or after `entry_grace` past the signal that made the ring a visit (the guest coming in); it ends the visit once `quiet_period` passes without a further door opening (`CLOSED`, `end` = that door opening, `end_reason` `door_then_quiet`). Otherwise the visit ends at `start + max_duration` (`end_reason` `max_duration`); the maximum wins when the quiet deadline would fall after it. Both half-open: a door opening exactly at the quiet deadline is too late. Deadlines are derived from the entry's signals and the current settings, so an open visit restored from the store needs no extra bookkeeping. While a visit is open, `DOOR_OPEN`, `DOOR_CLOSE`, `PRESENCE_ON`, `PRESENCE_OFF` and `LOCK` signals are appended to it (`SIGNAL_ADDED`); a door opening or presence that turns a pending ring into a visit is consumed by that visit and not appended to other open visits.

A `handle` call first runs `advance(signal.time)`, so deadlines before the signal fire first. Entries returned in Changes are the live objects; the runtime stores them.

Resident signals (ticket 03): the engine keeps resident signals of the last `resident_window` in memory only. They are not stored; a restart inside that window forgets them (accepted, the window is minutes). A `RING` with a resident signal in `[ring - resident_window, ring]` becomes a `RESIDENT_ARRIVAL` at once (one `CLASSIFIED` change, no `OPENED`): `reason` `resident_signal`, `start` = `end` = ring time, `signals` = the resident signals plus the ring, `certainty` None. A `RESIDENT` signal turns every pending ring into a `RESIDENT_ARRIVAL` (`end` = signal time) and every open uncertain visit with a ring inside its ring window (`ring <= signal < ring + ring_window`) as well; `end_reason` is cleared. Signal cap: an entry keeps at most `MAX_SIGNALS` (1000) signals. Beyond that the oldest door, presence and lock signals are dropped (never rings, `GUEST_*` signals or the signal that started the visit) and counted in `Entry.dropped_signals`; the renderer shows `… N older signals not kept`. A `CLASSIFIED` change whose entry has an `end` is final: the entry left `active_entries()`. Resident signals outside these cases change nothing and are not appended to visits.

Guest phones (ticket 05): `GUEST_HOME` / `GUEST_AWAY` signals carry `source` = the tracker entity id and `guest_id`; a signal for an unknown guest is ignored. `GUEST_HOME` with no open visit opens a certain `VISIT` (`OPENED`, `reason` `guest_phone`, one guest). With an open visit the guest joins it (`SIGNAL_ADDED`): an open certain visit is preferred, an open uncertain one becomes `CERTAIN` and keeps its start decision (`reason`). A guest already in an open visit only gets the signal appended. `GUEST_AWAY` is appended to every open visit that contains the guest. A certain visit has no max duration and ignores door quiet periods: it is open while the last signal of any known tracker is `GUEST_HOME`. Once every tracker is away its deadline is the latest away time plus `phone_grace`, and it ends there (`CLOSED`, `end` = that away time, `end_reason` `guests_left`). A guest stays in the visit's guest list for good but is *present* only until all their phones have been away for `phone_grace`: then the engine marks the guest as left (`rule_state["left_guests"]`, one `GUEST_LEFT` change at that deadline, which `next_deadline` includes) and `Entry.present_guest_ids` no longer lists them; a phone of the guest coming back unmarks them. The visit itself ends only when the last guest has left. A guest is a member of a visit by id; a rename updates the stored name the next time the guest is seen. A phone back before the deadline cancels it; at the deadline it is too late (half-open), the old visit closes and a new one opens. Trackers no longer listed in the guests count as away, so `set_guests` can make a visit due; the caller advances afterwards. A ring plus door or presence while a certain visit is open does not open an uncertain visit: the pending rings are reported as `CLOSED` and the door or presence signal is appended to the certain visit (`SIGNAL_ADDED`). A resident signal never turns a certain visit into a resident arrival.

Guest already home (lifecycle fix): `guest_present(guest_id, tracker, now)` is for a phone that is `home` at startup or when its guest is added, without a state change. It first advances to `now`. It does nothing for an unknown guest or when an open visit already has the guest and that visit already knows the tracker as home (restored visits are not duplicated). It appends a `GUEST_HOME` signal at `now` (`SIGNAL_ADDED`) when the visit has never seen the tracker (a second phone of the guest) or when the last signal of that tracker is `GUEST_AWAY` (the phone left and the phone grace was still running; the pending leave is cancelled). If the grace period had already run out, the old visit closes first and a new one opens. Otherwise it behaves like `GUEST_HOME` at `now` (joins an open visit), but a visit it opens has `reason` `guest_phone_at_start`. The runtime calls it for every `home` tracker of every guest in `async_start` and `async_set_guests`.

Guest left during downtime: `guest_absent(guest_id, tracker, now)` appends a `GUEST_AWAY` signal at `now` to every open visit whose last signal for that tracker is `GUEST_HOME` (`SIGNAL_ADDED`); otherwise it does nothing and does not advance. In `async_start` the runtime advances, then calls it for every guest tracker whose state exists and is neither `home`, `unavailable` nor `unknown`, so the phone grace and the end rule apply from the startup time (end = startup time, `guests_left`).

## Corrections and additions (ticket 09)

`core/effective.py` holds the only logic that applies a correction (calendar and sensor code only call it):

- `effective_kind(entry) -> EffectiveKind` (`PENDING_RING`, `VISIT`, `UNANSWERED_RING`, `RESIDENT_ARRIVAL`, `DELIVERY`): correction `resident` gives `RESIDENT_ARRIVAL`, `delivery` gives `DELIVERY`, `visit` gives `VISIT` (also for unanswered rings and resident arrivals), `unknown` and no correction keep the kind of the decision. `DELIVERY` exists only here; it is never stored as `Entry.kind`.
- `effective_guests(entry)`: profile names plus the correction's `guest_name` (compared with `normalize_name`, no duplicate). `effective_start` / `effective_end`: the correction's start and end, else the entry's.
- Visits calendar: effective kind `VISIT`. Rings calendar: `UNANSWERED_RING` and `DELIVERY`. Resident arrivals appear nowhere. `render_title` follows the effective kind (`Delivery` / `Lieferung`) and guests. An entry counts as open in the calendar while `effective_end` is `None`.
- `latest_entry(entries) -> Entry | None` (`core/latest.py`): the entry with the most recent stored `start` whose stored `kind` is `VISIT` or `UNANSWERED_RING`, open or closed. `PENDING_RING` and `RESIDENT_ARRIVAL` never count, by decision. The stored kind and start decide, not the correction, so a corrected entry stays the latest one and can be corrected again; on equal starts the entry stored last wins. Used for the optional `entry_id` of `correct_entry` and `add_note`, the latest entry sensor and the correction buttons.
- `Engine.close(entry_id, now)` ends an open `VISIT` (`CLOSED`, `end` = now, `end_reason` `corrected`). It returns `[]` for unknown ids, closed entries and pending rings. A closed visit gets no more signals, its deadline is gone.

Runtime methods (`GuestbookRuntime`, all raise `ServiceValidationError` with a translation key; the `entry_id` is a placeholder):

- `async_correct_entry(entry_id | None, kind: CorrectionKind, *, guest_name, start, end, note, source="action") -> Entry`: stores `Correction(kind, now, source, ...)` in `entry.correction` next to the decision (a later correction replaces the earlier one), saves, closes the visit in the engine for `resident` and `delivery`, fires `guestbook_visit_corrected` (`entry_id`, `kind`, `guest_name`, `guests`, `certainty`, `start`, `end`; guests, start and end are the effective values after the correction) and updates the entities. Without an `entry_id` (`None`) the entry is `async_latest_entry()`. Errors: `no_latest_entry` (no visit or unanswered ring stored), `unknown_entry`, `entry_pending` (a ring still in its window is not correctable), `end_before_start` (checked on the effective start and end).
- `async_add_visit(guests, start, end, note=None) -> Entry`: checks the times, builds the entry with `core.manual_visit(names, profiles, start, end, note, settings)` and stores it. The entry is a closed `VISIT`, `certainty` `certain`, `reason` `manual`, `settings` snapshot of the engine. Guest names are matched to the guest profiles with `normalize_name` (profile id and name); other names are free names with id `""`; duplicates and blank names are dropped. No bus events (it is not a live visit).
- `async_add_note(entry_id | None, note) -> Entry`: appends to `entry.notes`. Without an `entry_id` it notes the latest entry. Errors: `no_latest_entry`, `unknown_entry`.
- `async_latest_entry() -> Entry | None`: `core.latest_entry(entries)`.
- `async_press_button(kind: CorrectionKind) -> Entry`: `async_correct_entry(None, kind, source="button")`. For `VISIT` the name comes from `runtime.guest_name` (empty = no name) and is cleared after the correction succeeded; on an error the name stays. `guest_name` / `async_set_guest_name(name)` hold the text entity's value, so the text entity and the button share it; it is not stored in the entry.
- `async_entries(*kinds: EffectiveKind)` filters by effective kind. `async_open_visits()` and the current visit sensor use `effective_guests`.

Actions (`services.py`, schemas with `probatio`, descriptions in `services.yaml`, texts in `strings.json` and `translations/{en,de}.json`):

- `guestbook.correct_entry`: optional `entry_id` (default: the latest entry), `kind` (a `CorrectionKind` value), optional `guest_name`, `start`, `end`, `note`. `SupportsResponse.OPTIONAL`: with a response it returns `entry_id`, `kind`, `decision`, `guests`, `start`, `end` (effective, ISO). Start and end are only display overrides; an end on an open visit does not close it.
- `guestbook.add_visit`: optional `guests` (a name or a list of names; each element is a string by `cv.string`, not blank, trimmed and cut to `MAX_GUEST_NAME`), `start`, `end`, optional `note`.
- `guestbook.add_note`: optional `entry_id` (default: the latest entry), `note`.
- All use the first loaded entry (single config entry) and raise `not_loaded` when there is none. Naive datetimes count as local time.

## Renderer (ticket 07)

`core/render.py`, pure functions, texts in `de` and `en` (a region suffix is ignored, other languages fall back to `en`).

- `render_description(entry, language, names, tz) -> str`: `names` maps entity id to friendly name (missing ids show the entity id), `tz` is a `tzinfo`. One line per signal in time order, `HH:MM <name>: <what>` in local time. The source `action` reads "resident_unlock action". Presence on/off of one sensor is condensed to `<name> HH:MM–HH:MM` (placed at the on time); a stretch still on reads `<name> from HH:MM`, an off without an on in the entry reads `<name> until HH:MM`. No length limit. After a blank line: start reason, end reason, the correction (with kind, guest, start, end, note) and the notes; reason codes are translated, unknown codes show the reason detail.
- `render_title(entry, language)`: `Visit: Alex, Sam`, `Visit (uncertain)`, `Visit`, `Unanswered ring` and the German counterparts.
- The calendars call both with `hass.config.language`, the default time zone and the friendly names of the signal sources (`State.name`).

## Home Assistant APIs

Config flow schemas use `probatio` (as in Home Assistant 2026.10 core), not `voluptuous`. Entity ids: the Visits calendar belongs to a "Guestbook" service device, so it is `calendar.guestbook_visits`; the Rings calendar is `calendar.guestbook_rings`. Resident arrivals appear in no calendar. Signal time is `State.last_changed` of the new state. Changes from or to `unavailable`/`unknown` are ignored, except `unknown` to a timestamp on `event` entities. Resident signal entities fire on a change to `on`, `home` or `unlocked` or on a new `event` timestamp; lock entities (`locks` source, lock domain) emit a `LOCK` signal with the new state on every state change.

Action `guestbook.resident_unlock` (optional `source` text) is registered in `async_setup` (`services.py`). It hands `Signal(RESIDENT, now, "action", state=source)` to every loaded entry's runtime and raises `ServiceValidationError` (`not_loaded`) when no entry is loaded.

Guests (ticket 05): config subentries of type `guest` (`SUBENTRY_GUEST`) with data `name` and `trackers` (list of `device_tracker` entity ids, may be empty). The subentry id is the guest id. `GuestSubentryFlow` in `config_flow.py` has the steps `user` and `reconfigure`. The entry update listener (set up in `async_setup_entry`) rebuilds the guest list on every entry update and calls `SignalAdapter.async_set_guests` (re-subscribes the tracker listeners) and `GuestbookRuntime.async_set_guests` (engine, advance, listeners). No reload, so open visits survive guest changes. The adapter keeps the last real state of every tracker (`unavailable` and `unknown` don't count; seeded from the state machine). A new real state `home` after a last known state other than `home` (or none) gives `GUEST_HOME`; a real state other than `home` after `home` gives `GUEST_AWAY`. So `home`, `unavailable`, `not_home` ends a visit like `home`, `not_home`. With no last known state (the phone was unavailable since startup) a non-home state also gives `GUEST_AWAY`; the engine only appends an away signal to a visit that last saw that tracker home. `SignalAdapter(hass, config, guests, on_signal)`. The Visits calendar entity (`event`) reports an open visit with an end one minute after now so the entity state is `on`; `async_get_events` keeps the end at now. The title is `Visit: <names>` when guests are known, otherwise `Visit (uncertain)`.

Sensors (ticket 06): `entity.py` holds `GuestbookEntity` (has_entity_name, no polling, registers a runtime listener, device = the "Guestbook" service device unless a device is passed); calendars and sensors derive from it. `binary_sensor.guestbook_visit_active` is on while `runtime.async_open_visits()` is not empty. `sensor.guestbook_current_visit` shows the most recent open visit: state = comma-joined guest names (cut with an ellipsis to stay below 250 characters), the translated word "Unknown guest" (`unknown_guest(language)` in `core/messages.py`, `hass.config.language`) for a visit without guests, `None` (HA shows unknown) when no visit is open; attributes `entry_id`, `start` (ISO), `certainty` only while a visit is open. One `GuestSensor` per guest subentry (`binary_sensor.<guest>_visiting`), added with `config_subentry_id`, on while the guest is *present* in an open visit (`Entry.present_guest_ids`); it goes off when the guest left a visit that continues with someone else. HA requires a device to belong to one subentry, so each guest gets its own service device (identifier `(DOMAIN, subentry_id)`, name = guest name). The binary sensor platform has its own entry update listener that adds sensors for new guests and renames the device of renamed ones; `async_remove_subentry` removes the entities and the device. All translation keys live under `entity.binary_sensor` (`visit_active`, `guest`) and `entity.sensor` (`current_visit`).

Correction entities (all on the Guestbook device, platforms `sensor`, `text`, `button`): `sensor.guestbook_latest_entry` (`LatestEntrySensor`, translation key `latest_entry`) shows `render_title(latest_entry, hass.config.language)` cut to 250 characters, attributes `entry_id`, `start`, `end` (null while open), `kind` (the effective kind) and `corrected` (a correction exists); unknown without a correctable entry. `text.guestbook_guest_name` (`GuestNameText`, key `guest_name`, `TextMode.TEXT`, max 64, min 0, empty by default) keeps its value in the runtime and restores it with `RestoreEntity` (the states `unknown` and `unavailable` are ignored). `CorrectionButton` creates one button per `CorrectionKind` (keys `resident`, `delivery`, `visit`, `unknown`; entity ids `button.guestbook_that_was_me`, `button.guestbook_delivery`, `button.guestbook_visit`, `button.guestbook_don_t_know` in English); a press calls `runtime.async_press_button(kind)` and so raises the translated `no_latest_entry` error when nothing can be corrected. The correction source is `button`. All of them update through the runtime listener.

## Runtime

`GuestbookRuntime` lives in `entry.runtime_data`. Code that reads it types the entry as `GuestbookConfigEntry` (`ConfigEntry[GuestbookRuntime]`, defined in `__init__.py`; modules imported by `__init__.py` import it under `TYPE_CHECKING`). It owns the engine and the store, turns adapter signals into `engine.handle`, schedules one timer at `engine.next_deadline()`, saves changed entries, fires bus events, and calls registered listeners (`async_add_listener(cb) -> unsub`) so entities update. `async_open_visits()` returns the open visits, most recent first. Corrections and additions go through runtime methods, not straight to the store.

## Pushes (ticket 10)

Push options (`entry.options`, step `pushes` of the options flow, see Settings): `phones` (list of device ids, `DeviceSelector` for integration `mobile_app`, multiple), `notify_entities` (list of `notify` entity ids), `push_arrival` (on), `push_end` (on), `push_correction` (on), `push_unanswered_ring` (off), `push_open_path` (text, empty by default). Keys and defaults are in `const.py` (`PUSH_DEFAULTS`). The notifier reads the options at send time, so a change needs no reload; the entry update listener ignores updates that leave the guest list as it was, so options changes never touch open visits.

`Notifier(hass, entry, runtime)` registers with `runtime.async_add_change_listener(cb(Change))`, which receives every Change the runtime applies. Triggers:

- Arrival: `OPENED` or `CLASSIFIED` change of an open visit, except a visit whose start `reason` is `guest_phone_at_start` (restart or newly added guest; the bus event `guestbook_visit_started` still fires and the end push is sent).
- End: `CLOSED` change of a visit, except when `end_reason` is `corrected`. A visit reclassified as a resident arrival is not a visit any more and gets no end push.
- Unanswered ring: `CLASSIFIED` change to `UNANSWERED_RING`.
- Arrival and end only when none of the config entry's `residents` (`person` entities) is `home`; with no residents selected they are always sent. The correction question and the unanswered ring ignore residents.

Targets: a phone is a `mobile_app` device. The notifier reads only the device registry. A device counts as a phone when one of its identifiers has the domain `mobile_app`. It calls the legacy service `notify.mobile_app_<slugify(device.name)>` with the original `device.name` (the name `mobile_app` registered; `name_by_user` is ignored, so renaming the device changes nothing) and checks `hass.services.has_service` first. The config entry data of `mobile_app` is never read. If the device is gone, is not a mobile_app device or the service does not exist, the phone is skipped with a debug log. Phone payload: `title`, `message`, and `data` when needed. With `push_open_path` set (trimmed, not empty) every phone push has `data.url` (iOS) and `data.clickAction` (Android) with that path, so a tap opens that dashboard; the correction question adds `tag` and `actions` to the same `data`. Text-only targets never get the path. Notify entities get one `notify.send_message` call (`entity_id` list, `title`, `message`); the message ends with `Entry id: <id>` (`Eintrags-ID` in German). Calls run as background tasks of the config entry (`entry.async_create_background_task`), so unloading the entry cancels pushes still in flight; a `HomeAssistantError` is logged as a warning and does not stop the other targets.

Texts live in `core/messages.py` (`de` and `en`, other languages fall back to `en`, region ignored) and use `hass.config.language`: `push_title(kind, language)`, `push_message(kind, language, guests, entry_id=None, *, ios_hint=False)` (with an `entry_id` the id is appended; for the correction question also a hint to use `guestbook.correct_entry`; with `ios_hint` the correction question ends with "Press and hold to answer." / "Zum Antworten lange drücken." because iOS shows the buttons only on a long press; the notifier sets it for phones that are not Android).

## Correction question (ticket 11)

The notifier sends the question (`PushKind.CORRECTION`) on the same `OPENED`/`CLASSIFIED` change as the arrival push, for every open `UNCERTAIN` visit, when `push_correction` is on, whether or not a resident is home. Certain visits and unanswered rings get none.

- Phone payload: `title`, `message` (on iOS with the long-press hint, not on Android), `data.tag` = the entry id (a later push with the same tag replaces it) and `data.actions` from `correction_actions(language, entry_id, token, android=...)`: ids `GUESTBOOK_<KIND>_<entry_id>_<token>` for `RESIDENT`, `DELIVERY`, `VISIT`, `UNKNOWN` (titles "That was me", "Delivery", "Visit", "Don't know" and the German ones). `VISIT` has `behavior: textInput`, `textInputButtonTitle` and `textInputPlaceholder`. Android gets the first three. The platform comes from the device registry: `manufacturer == "Apple"` means iOS, any other manufacturer is treated as Android.
- Notify entities get the text with `Entry id: <id>` and the hint to answer with `guestbook.correct_entry`; no buttons.
- The notifier listens to the bus event `mobile_app_notification_action`. `parse_action_id(action) -> (CorrectionKind, entry_id, token) | None` accepts only the four ids above (upper case, non-empty entry id and token; entry ids contain no underscore, the token is the rest). A match calls `runtime.async_answer_question(entry_id, token, kind, guest_name=reply_text for VISIT)`. Question tokens: when the notifier sends a correction question it calls `runtime.async_ask_question(entry)`, which sets `entry.question_token` to `secrets.token_urlsafe(8)` (replacing an earlier one) and saves it, so it survives a restart. An answer is accepted only when its token equals the entry's pending token (constant-time compare); the token is then consumed (set to None) and the correction is saved with source `push`. A wrong, missing or used token, foreign action ids, unknown entries and a `ServiceValidationError` (ring still in its window) are ignored; the reason is only logged at debug level. `guestbook.correct_entry` needs no token. `to_jsonl` leaves out `question_token` like `rule_state`. The listener is removed on unload.

## Export and retention (ticket 13)

- `core/archive.py` (pure): `expired_entries(entries, now, retention)` returns the closed entries whose `end` is older than `now - retention` (an entry ending exactly at the cutoff stays; entries with `end` None, i.e. open visits and pending rings, are never expired). `entries_in_range(entries, start, end)` sorts by start and keeps `start <= entry.start < end` (a missing bound is open). `to_jsonl(entries)` is one `Entry.to_dict()` JSON object per line, without `rule_state` and `question_token` (they stay in the storage). `entries_in_range` skips pending rings.
- Retention is the option `retention` (days, default 365, `settings.py` maps it to `Settings.retention`). `GuestbookRuntime.async_purge(now)` removes the expired entries from the store; it runs in `async_start` and every day (`async_track_time_interval`, `PURGE_INTERVAL`). A changed retention applies at the next run; saving the option does not purge at once.
- `guestbook.export` (optional `start`, `end`; `SupportsResponse.OPTIONAL`; registered with `async_register_admin_service`, so only admin users may call it) calls `GuestbookRuntime.async_export(start, end)`. The file is `<config>/guestbook/guestbook-<UTC %Y%m%dT%H%M%SZ>.jsonl`, written in the executor (`hass.config.path`); the file is created exclusively (mode `x`); on `FileExistsError` (another export in the same second, even a concurrent one) the next suffix `-2`, `-3` is tried, so a file is never overwritten. The response is `{"path": ..., "count": ...}`. Naive datetimes count as local time. The export contains the stored entries in range, including open visits but not pending rings.

## Settings and repairs (ticket 14)

`GuestbookOptionsFlow` is a menu (`init`) with four steps; each step saves on its own and finishes the flow:

- `sources`: `doorbells`, `doors`, `presence`, `locks` (the selectors of the config flow; the setup form `SOURCES_SCHEMA` is built from the `sources` and `residents` step schemas). `residents`: `residents`, `resident_signals`. Both write into `entry.data` (`async_update_entry`), where the config flow put the sources; the options stay as they are. `SOURCE_KEYS` in `const.py` lists the six source keys.
- `rules` writes numbers into `entry.options`: `ring_window`, `resident_window`, `quiet_period`, `entry_grace`, `phone_grace` (minutes), `max_duration` (hours), `retention` (days). `settings.py`: `settings_from_options(options) -> Settings` (a missing key keeps the core default), `rule_defaults()` (defaults in the option units, taken from `Settings()`).
- `pushes` writes the push options. Steps merge their fields into the existing options, so the rules survive a push change and the other way round.

The entry update listener (`__init__.py`) compares what changed and applies it without a reload: new settings go to `GuestbookRuntime.async_set_settings` (engine `set_settings`, advance, entities refresh; open visits keep running and their deadlines follow the new numbers, a deadline that has already passed under the new numbers fires at once), new sources to `SignalAdapter.async_set_sources` (re-subscribes) and `SourceMonitor.async_refresh`, new guests as before. Entries and open visits are never touched; `entry.runtime_data` stays the same object.

Missing sources (`repairs.py`): `SourceMonitor` raises one non-fixable warning issue per selected source entity (all `SOURCE_KEYS`) that has neither a state nor an entity registry entry. Issue id `missing_source_<entity_id>`, translation key `missing_source`, placeholder `entity_id`. It checks once Home Assistant has started (`async_at_started`, so late integrations do not raise issues at boot), when the selection changes, and when a selected entity gets or loses its state or registry entry. Issues of deselected or returned entities are deleted; unloading the entry deletes all of them. Sources are independent: an unavailable or missing source never stops the signals of the others (each has its own state listener).

## Guest suggestion (ticket 12)

- `GuestSuggestions` (`repairs.py`) listens to the bus event `guestbook_visit_corrected`. For a correction of kind `visit` with a non-empty `guest_name` that matches no guest profile (trimmed, case-insensitive) it creates a fixable, persistent warning issue: id `guest_suggestion_<name casefolded>`, translation key `guest_suggestion`, placeholder `name`, data `{"entry_id": <config entry id>, "name": ..., "visit_id": <visit entry id>}`. Pushes and actions both end in that event. The same name again updates the one issue (latest visit). Other kinds (`delivery`, `resident`, `unknown`) never raise it, even with a name.
- The issue is deleted when a guest with that name exists: on every guest change (entry update listener), at startup, and by the fix flow. It is also deleted when its visit is gone: `GuestSuggestions.async_cleanup` checks `visit_id` against the stored entries at startup and after every retention purge (`GuestbookRuntime.async_add_purge_listener`). Removing the config entry deletes all issues of Guestbook (`async_remove_entry`).
- Fix flow (`async_create_fix_flow` in `repairs.py` is the repairs platform): `GuestSuggestionFlow`. `async_step_init` hands over to the step `guest` (Home Assistant passes the issue id as `user_input` of the first call). The form `guest` shows the name in the description (`{name}`, not editable) and one optional `device_tracker` selector, `trackers`, with the preselection as suggested value (so the user can clear it). Submitting calls `hass.config_entries.async_add_subentry` with a `guest` subentry (`name`, `trackers`), which the entry update listener picks up like any new guest. If the entry is not loaded the flow aborts with `not_loaded`; if the guest exists meanwhile, nothing is added and the issue is still removed.
- Preselection (`async_suggested_trackers`): `device_tracker` entities known to the state machine, minus the trackers linked to any guest, minus resident trackers (`device_tracker` entries of `resident_signals` and the `device_trackers` attribute of the selected `person` residents), that were `home` at any time between the effective start and end of the visit (end None: now). The history comes from the recorder (`get_significant_states` with the start state, in the recorder executor) when the `recorder` component is loaded (`after_dependencies` in the manifest). Without the recorder, without the visit entry (purged) or when the recorder query fails, the trackers that are `home` now are used. Known limit: a device that is always home (a printer, a TV) is preselected too; the user removes it in the form.

## Storage

One `Store` key `guestbook.entries`, version 1: `{"entries": [Entry.to_dict(), ...]}`. Delayed save (a few seconds); flush on unload. A stored item that cannot be read is skipped with a warning at load; it is gone with the next save. `Entry.from_dict` also checks what the engine relies on: every guest is a dict with a text `id` and `name`, and an open pending ring has a timezone-aware ISO `rule_state["deadline"]`; otherwise it raises `ValueError` and the item is skipped like any broken one.

## Events

`guestbook_visit_started`, `guestbook_visit_event`, `guestbook_visit_ended`, `guestbook_visit_corrected` (names in `const.py`).

The runtime fires them from the Changes of entries of kind `VISIT` (ticket 08). Payload values are JSON-safe; guests are names, times are ISO strings (UTC).

- `guestbook_visit_started`: `OPENED` or `CLASSIFIED` change of an open visit. `entry_id`, `guests`, `certainty`, `start`.
- `guestbook_visit_event`: `SIGNAL_ADDED` change of a visit. `entry_id`, `guests`, `certainty`, `signal` (SignalKind value), `source` (entity id), `time`. The signal that turns a ring into a visit is part of `started` and not repeated. A guest phone joining an open visit is a `guest_home` event.
- `guestbook_visit_ended`: `CLOSED` change of a visit (also when a correction to resident or delivery closes an open visit, `reason` `corrected`). `entry_id`, `guests`, `certainty`, `start`, `end`, `duration` (whole seconds), `reason` (the end reason code: `door_then_quiet`, `max_duration`, `guests_left`, `corrected`). A visit that already fired `started` and is then reclassified as a resident arrival fires `ended` too, with `reason` `resident_arrival` and the data of the visit as it was (certainty `uncertain`).
- `guestbook_visit_corrected` (ticket 09): `entry_id`, `kind` (the correction kind), `guest_name`, `guests` (effective names), `certainty`, `start`, `end` (effective, ISO, `end` may be null); fired by `correct_entry` for every entry kind.
- Resident arrivals and unanswered rings that never fired `started` fire nothing.

## Testing

- Core tests build signals with a helper `at("14:02")` on a fixed date.
- Integration tests set states with `hass.states.async_set`, move time with `async_fire_time_changed` and `freezer`, read calendars through `calendar.get_events` or the entity, and use `MockConfigEntry`.
- Run: `.venv/bin/pytest -q`, `.venv/bin/ruff check custom_components tests`.
