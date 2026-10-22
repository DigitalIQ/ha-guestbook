# Spec: Guestbook

**Status:** ready-for-agent
**Domain:** `guestbook`
**Glossary:** [GLOSSARY.md](GLOSSARY.md)

## Problem Statement

Home Assistant users who want a record of who visited them have no ready-made tool. Typical home-made automations write visit logs into `input_text` helpers and calendar events. `input_text` and entity states stop at 255 characters, so the log gets cut off. Presence sensor changes flood the text, and the important lines (who came, when the door opened) are lost.

The user also wants more than a log. They want to know right now whether a visit is going on and who is there, so automations can react. They want a push when a visit starts while they are away. And the rules that decide "this was a visit" are never perfect: the user's own ring at the door, a parcel delivery or a guest without a phone all look similar. Today there is no way to tell the system it was wrong, and no data to improve the rules with.

## Solution

Guestbook is a custom integration, installable through HACS. The user selects their doorbell, door contacts, presence sensors, locks and resident signals in the UI. They add guests with a name and the guest's phone (as a Wi-Fi `device_tracker`).

Guestbook then turns raw signals into visits:

- A guest's phone joins the Wi-Fi: a certain visit starts. It ends when the last phone leaves.
- Someone rings and then the door opens or presence is detected, with no resident signal: an uncertain visit starts. It ends at the next door opening that is followed by a quiet period, or after a maximum duration.
- A ring with a resident signal close to it is the resident coming home. It is never a visit.
- A ring with no door opening and no presence is an unanswered ring.

Every visit becomes one event in a visits calendar, from arrival to departure, with the full chronological log in the description and presence changes condensed. Unanswered rings go to a separate rings calendar. Sensors show whether a visit is active, the current visit, and one binary sensor per guest. Bus events let users build their own automations. Pushes go to selected phones and notify entities. For uncertain visits the phone gets a correction question with buttons. All data stays local, in Guestbook's own storage. A JSONL export holds the raw signals, the decision, the reason and the user's correction, so the rules can be tuned offline.

## User Stories

### Setup

1. As a Home Assistant user, I want to install Guestbook from HACS as a custom repository, so that I do not have to copy files by hand.
2. As a user, I want to set up Guestbook from the integrations page with a guided form, so that I never edit YAML.
3. As a user, I want to select one or more doorbell entities (`event` or `binary_sensor`), so that rings from any doorbell brand are recognized.
4. As a user, I want to select one or more door contacts, so that door openings are recognized.
5. As a user, I want to select one or more presence or motion sensors, so that someone inside the home is recognized even without a door contact.
6. As a user, I want to select one or more locks, so that lock changes appear in the visit log.
7. As a user, I want to select the residents as `person` entities, so that Guestbook knows who lives here.
8. As a user, I want to select entities that count as resident signals (for example a fingerprint event, a resident phone tracker, a "lock opened by resident" sensor), so that my own arrivals are never recorded as visits.
9. As a user, I want every source to be optional, so that Guestbook works with whatever hardware I have.
10. As a user, I want to change my source selection later without losing data, so that I can add new hardware.
11. As a user, I want to see the UI in German or English, following my Home Assistant language, so that I understand every field.

### Guests

12. As a user, I want to add a guest from the Guestbook entry page with a name, so that visits can show who came.
13. As a user, I want to link one or more phones (`device_tracker` entities) to a guest, so that the guest is recognized when their phone joins my Wi-Fi.
14. As a user, I want to edit or remove a guest later, so that the list stays correct.
15. As a user, I want Guestbook to suggest a new guest when I name an unknown guest in a correction, so that I do not have to remember to add them.
16. As a user, I want that suggestion to list phones that joined the Wi-Fi during that visit and are not linked to anyone, so that linking the right phone is one click.

### Visit detection

17. As a user, I want a visit to start when a guest's phone joins the Wi-Fi, so that guests with phones are logged without any action.
18. As a user, I want a phone visit to end when the last guest phone of that visit has left for longer than a grace period, so that short Wi-Fi drops do not split a visit.
19. As a user, I want two guests arriving at overlapping times to be one visit, so that the calendar shows one event per get-together.
20. As a user, I want a ring followed by a door opening or presence within the ring window to start an uncertain visit, so that guests without phones are logged.
21. As a user, I want a ring alone never to count as a visit, so that postal deliveries do not fill my calendar.
22. As a user, I want a ring with a resident signal shortly before or after it to count as a resident arrival, so that my own ringing and fingerprint opening are not visits.
23. As a user, I want to trigger a resident signal from my own automation with the action `guestbook.resident_unlock`, so that I can connect any lock or fingerprint reader, even ones Home Assistant cannot attribute to a user.
24. As a user, I want an uncertain visit to end at the next door opening that is followed by a quiet period without another door opening, so that the end time matches the guest leaving.
25. As a user, I want an uncertain visit to end after a maximum duration if no end is detected, so that a forgotten visit does not run forever.
26. As a user, I want a guest phone that joins during an uncertain visit to make that visit certain and add the guest, so that I get one correct visit, not two.
27. As a user, I want every rule number (ring window, resident window, quiet period, grace period, maximum duration) to be adjustable in the options, so that I can tune the rules to my home.
28. As a user, I want visits that are open during a Home Assistant restart to continue after the restart, so that a restart does not split or lose a visit.
29. As a user, I want each entry to store the reason why the rules decided what they decided, so that I can understand wrong decisions.

### Calendars

30. As a user, I want a visits calendar entity with one event per visit, from arrival to departure, so that any calendar card shows my visits.
31. As a user, I want an ongoing visit to show in the calendar with the end at "now", so that I see current visits too.
32. As a user, I want the event title to name the guests, or say "Visit (uncertain)" when nobody is known, so that I can read the calendar at a glance.
33. As a user, I want the event description to hold the full chronological log of the visit with no length limit, so that nothing is cut off.
34. As a user, I want presence changes condensed into one line per sensor and stretch (for example "Living room presence 14:02–14:40"), so that the log stays readable.
35. As a user, I want a separate rings calendar for unanswered rings and deliveries, so that I can show or hide them without cluttering the visits calendar.
36. As a user, I want resident arrivals to be stored but not shown in any calendar, so that the export still has them for tuning.

### Sensors

37. As a user, I want a binary sensor "visit active", so that automations can react to any visit.
38. As a user, I want a sensor "current visit" whose state names the guests (or says unknown) and whose attributes hold the visit id, start and certainty, so that dashboards can show who is here.
39. As a user, I want one binary sensor per guest that is on while that guest is visiting, so that I can build automations for a specific guest.
40. As a user, I want sensor attributes to stay small, so that the recorder keeps storing them.

### Events

41. As an automation author, I want the bus event `guestbook_visit_started` with the visit id, guests, certainty and time, so that I can react to arrivals.
42. As an automation author, I want the bus event `guestbook_visit_event` for every signal added to an open visit, so that I can react to details such as a door opening during a visit.
43. As an automation author, I want the bus event `guestbook_visit_ended` with the visit id, guests, start, end and duration, so that I can react to departures.
44. As an automation author, I want the bus event `guestbook_visit_corrected` when a correction is saved, so that I can sync corrections elsewhere.

### Notifications

45. As a user, I want to select phones with the Home Assistant Companion app as push targets, so that I get pushes with buttons.
46. As a user, I want to select additional `notify` entities (for example a messenger) as text-only targets, so that I can use other channels.
47. As a user, I want to switch each push type on or off: arrival (default on), end (default on), correction question (default on), unanswered ring (default off), so that I only get what I care about.
48. As a user, I want arrival and end pushes only when none of the residents is home, so that I am not told about a visit I am part of.
49. As a user, I want the correction question for every uncertain visit, whether I am home or not, so that the data gets corrected.
50. As a user, I want the correction question to have the buttons "That was me", "Delivery", "Visit" (with a text field for the name) and "Don't know", so that I can answer in one tap.
51. As an Android user, I want the "Don't know" button to be left out because Android shows at most three buttons, so that the other buttons still work.
52. As a user, I want my button answer to be saved as a correction to the right visit, so that the calendar and export update at once.
53. As a user with a text-only target, I want the push to include the visit id, so that I can correct it with the action.

### Corrections and additions

54. As a user, I want the action `guestbook.correct_entry` with the entry id (optional, see story 69), the kind (`resident`, `delivery`, `visit`, `unknown`), an optional guest name, optional start and end, and an optional note, so that I can fix any entry.
55. As a user, I want a visit corrected to `resident` to disappear from the visits calendar but stay in the storage and the export, so that the calendar is right and the tuning data is complete.
56. As a user, I want a visit corrected to `delivery` to move to the rings calendar, so that deliveries are shown where they belong.
57. As a user, I want an unanswered ring corrected to `visit` to move to the visits calendar, so that missed visits can be repaired.
58. As a user, I want the action `guestbook.add_visit` with guests, start, end and an optional note, so that I can log a visit the sensors missed.
59. As a user, I want the action `guestbook.add_note` to add a free-text note to an entry, so that I can add context.
60. As a user, I want the original decision and reason kept next to my correction, so that the export shows where the rules were wrong.

### Export and data

61. As a user, I want the action `guestbook.export` to write a JSONL file to `/config/guestbook/`, one line per entry with signals, decision, reason, correction and the settings at decision time, so that I can tune the rules with an AI assistant.
62. As a user, I want to limit the export to a date range, so that files stay small.
63. As a user, I want all data to stay on my Home Assistant, with no cloud and no telemetry, so that my guests' privacy is protected.
64. As a user, I want entries older than the retention period (default 365 days, adjustable) to be deleted automatically, so that I do not keep personal data longer than needed.
65. As a user, I want the README to explain what personal data is stored and how to delete it, so that I can use Guestbook responsibly.

### Health

66. As a user, I want a repair issue when a selected source entity no longer exists, so that I notice broken setups.
67. As a user, I want Guestbook to keep working when one source is unavailable, so that one broken sensor does not stop the log.

### Migration

68. As a user switching from a home-made automation, I want to run Guestbook in parallel with it, so that I can compare both before switching off the old one.

### Correcting from the Home Assistant UI

69. As a user, I want `guestbook.correct_entry` and `guestbook.add_note` to work without an entry id and then act on the latest entry, so that I never have to look up an id.
70. As a user, I want a sensor "Latest entry" that shows the title of that entry with its id, times, effective kind and whether it was corrected, so that I see what a correction will change.
71. As a user, I want the buttons "That was me", "Delivery", "Visit" and "Don't know" in Home Assistant, so that I can correct the latest entry from any dashboard.
72. As a user, I want a text field "Guest name" that the "Visit" button uses and then clears, and that keeps its value across restarts, so that I can name the guest before I press.
73. As a user, I want a clear error when there is no entry to correct, so that a press never fails silently.
74. As an iPhone user, I want the correction question to tell me to press and hold, since iOS shows the buttons only on a long press, so that I find the answer buttons.
75. As a user of a Companion app phone, I want a tap on a push to open my Guestbook dashboard (option "Open dashboard path"), so that I can answer without searching for the dashboard.

## Implementation Decisions

### Modules

- **Rule core** (pure Python, no Home Assistant imports). Input: a stream of signals with timestamps, the guest list and the settings. Output: entries and lifecycle changes (visit started, signal added, visit ended, ring classified). It never reads the clock. Time moves only through signals and an explicit `advance(now)` call. It reports its next deadline (end of a ring window, end of a quiet period, maximum duration) so the caller can schedule a timer. It can be rebuilt from stored open entries after a restart.
- **Store** (Home Assistant `Store`, JSON under `.storage/`, delayed saves). Holds all entries, open and closed, with their signals, decision, reason, correction, notes and a settings snapshot. Purges entries older than the retention period once a day and at startup. Schema has a version number for later migrations.
- **Signal adapter** (integration layer). Subscribes to state changes of the selected sources and guest traits, normalizes them into signals and feeds the rule core. Ignores changes from or to `unavailable` and `unknown`. Doorbells: an `event` entity fires on every new event timestamp; a `binary_sensor` fires on `off`→`on`. Resident signals from entities fire on a change to `on`, `home`, `unlocked` or a new `event` timestamp.
- **Calendars**: two read-only `calendar` entities, "Visits" and "Rings". Built on demand from the store in `async_get_events`. Event `uid` is the entry id. Times in UTC.
- **Description renderer**: turns an entry into the readable chronological log in the Home Assistant language (de or en). Condenses presence on/off pairs per sensor into one line with a time range.
- **Sensors**: `binary_sensor` visit active, `sensor` current visit, one `binary_sensor` per guest. Attributes only small scalars and ids, never the log.
- **Events**: `guestbook_visit_started`, `guestbook_visit_event`, `guestbook_visit_ended`, `guestbook_visit_corrected`. Payload: `entry_id`, `guests` (names), `certainty`, timestamps, and for `guestbook_visit_event` the signal kind and source entity id.
- **Notifier**: sends pushes. Companion app phones are selected as `mobile_app` devices and called through the legacy `notify.mobile_app_<device>` action, because only that action accepts `data.actions` (buttons). Text-only targets are `notify` entities called with `notify.send_message`, which has no `data`. Listens to `mobile_app_notification_action` and maps the action id (which contains the entry id) to a correction. The "Visit" button uses `behavior: textInput`; the reply text is the guest name. The phone's OS comes from the mobile_app device; on Android the "Don't know" button is left out (three-button limit). On iOS the question text ends with a hint to press and hold, because iOS shows action buttons only on a long press. The option `push_open_path` (empty by default) adds `url` (iOS) and `clickAction` (Android) to every phone push, so a tap opens that dashboard path.
- **Latest entry**: the entry that corrections without an entry id, the buttons and the Latest entry sensor mean. It is the entry with the most recent start whose stored decision is `visit` or `unanswered_ring`, open or closed. Pending rings and resident arrivals are never chosen, by decision: a pending ring cannot be corrected yet, and a resident arrival is not something the user wants to correct by accident. The stored decision and start count, not the correction, so a corrected entry stays selected and can be corrected again. The selection is a pure function in the rule core. With no such entry the actions and buttons raise a translated error.
- **Correction entities**: `sensor` Latest entry (state: the rendered title, cut below 255 characters; attributes `entry_id`, `start`, `end`, `kind`, `corrected`), `text` Guest name (max 64, restored after a restart, empty by default) and four `button` entities that correct the latest entry with the correction source `button`. The Visit button takes the guest name from the text entity (empty: a visit without a name) and clears it after a successful press.
- **Actions**: `guestbook.resident_unlock`, `guestbook.correct_entry`, `guestbook.add_visit`, `guestbook.add_note`, `guestbook.export`. All with a `services.yaml` description and translations.
- **Config flow**: one config entry per Home Assistant instance (`single_config_entry`). Sources and residents in the setup form; sources, residents, settings, push targets and push switches in the options flow.
- **Guests as config subentries** of type `guest`, with a `user` and a `reconfigure` step. Fields: name and a list of `device_tracker` entities.
- **Guest suggestion**: when a correction names a guest without a profile, a fixable repair issue offers to create the guest, with the unlinked `device_tracker` entities that were `home` during that visit preselected.
- **Repairs**: one issue per missing source entity, removed when the entity is back or deselected.

### Rules (default settings in brackets)

- Ring window [5 min]: a door opening or presence on within this time after a ring turns the ring into a visit. A signal exactly at the end of the window still counts. This holds even when the clock reaches the end of the window first (the timer waits a second longer).
- Resident window [3 min]: a resident signal from this time before a ring until the end of the ring window makes the ring a resident arrival. The rule core remembers resident signals in memory only, so a restart forgets them.
- Signal cap [1000 per entry]: an open visit that never ends (a guest phone that stays home for weeks) must not grow without bound. Beyond the cap the oldest door, presence and lock signals are dropped; rings, guest phone signals and the signal that started the visit are kept. The entry counts the dropped signals (`dropped_signals`) and the description says "… N older signals not kept".
- A door opening or presence with no ring before it starts nothing (residents leaving and coming back).
- A ring plus a door opening or presence while a certain visit is open does not start a new entry. Both are added to that visit.
- Quiet period [10 min]: an uncertain visit ends at the first door opening after which the door stays closed for this long. The end time is that door opening. Only door openings count for this check; door closings are ignored. Entry grace [2 min]: a door opening in the first 2 minutes after the signal that turned the ring into a visit (the guest coming in) does not count. The grace counts from that signal, not from the ring.
- Maximum duration [4 h]: an uncertain visit with no detected end ends at start plus this time, reason `max_duration`.
- Phone grace period [5 min]: a guest phone must stay away this long before it counts as leaving. The end time is the moment it went away.
- A guest with several phones has left when all of them are away for the phone grace period; a visit that already had one phone of the guest learns of another phone that is home at startup. In a visit that goes on with another guest, the guest who left is no longer present (their binary sensor goes off) but stays in the visit's guest list.
- A certain visit ends when all its guest phones have left. A guest phone joining an open uncertain visit makes it certain; its later end follows the phone rule.
- A guest phone joining while a certain visit is open adds the guest to that visit.
- Pushes "arrival" and "end" only when no selected resident `person` is `home`.

### Data shape of an entry

`id`, `kind` (the decision of the rules: `visit`, `unanswered_ring`, `resident_arrival`, and `pending_ring` while a ring waits for its window to end), `start`, `end` (null while open), `certainty`, `guests` (guest ids and names), `signals` (kind, source entity id, time, state), `reason` (`code`, `detail`; why the entry got its kind), `end_reason` (`code`, `detail`; why a visit ended), `correction` (`kind`, `guest_name`, `start`, `end`, `note`, `time`, `source`: `push`, `action` or `button`), `notes`, `settings` snapshot. The storage also keeps `rule_state`, private bookkeeping of the rule core. The export writes this shape, one entry per line, without `rule_state` and without pending rings.

### Platform

- Minimum Home Assistant 2026.10. Brand icons ship in the integration's own `brand/` folder (supported since 2026.3).
- `iot_class: calculated`, `integration_type: service`, no Python requirements.
- HACS files: `hacs.json` (name, minimum HA version), `manifest.json` (domain, name, version, documentation, issue_tracker, codeowners, config_flow), `brand/icon.png` 256 px and `icon@2x.png` 512 px, README in English, MIT `LICENSE`, translations `en` and `de`.
- CI: HACS action (`hacs/action@main`, category integration), Hassfest (`home-assistant/actions/hassfest@master`), tests and ruff on Python 3.14.

## Testing Decisions

- Tests check external behavior only: what a user or automation sees. They never inspect private attributes or call private functions.
- **Seam 1, rule core**: feed signals with fixed timestamps and settings, assert the resulting entries, decisions, reasons and next deadlines. This holds the many rule cases (resident arrival, unanswered ring, quiet period, phone grace, merge of phone and uncertain visit, maximum duration). No Home Assistant needed, fast.
- **Seam 2, integration in a test Home Assistant** with `pytest-homeassistant-custom-component`: create fake source entities with `hass.states.async_set`, move time with `async_fire_time_changed`, then assert calendar events (through the calendar API), sensor states, fired bus events, stored data after a restart, called notify actions (mocked services) and exported files. Config flow, options flow and guest subentries are also tested here.
- Test data uses invented names and entity ids only (for example guest "Alex", `binary_sensor.front_door`).
- Prior art: the sister project Presence Planner uses the same test package, `asyncio_mode = auto`, and a split between pure core tests and integration tests.
- Each ticket is built test-first (red, green, refactor).

## Out of Scope

- An own dashboard card. Display uses existing cards (Calendar Card Pro, Chronicle Card). A card may come later as a separate repository.
- Self-learning rules. Tuning happens offline with the export.
- Import of old calendar events from a previous automation.
- Detection of a specific lock's fingerprint reader. Guestbook offers the generic resident signal input; how a specific lock produces it is the user's setup.
- Unknown phones as visit triggers. Only phones linked to a guest start visits.
- Cloud sync, telemetry, multi-home setups.
- Editing events in the calendar UI. Changes go through the actions and the correction push.
- Submission to the HACS default list. First release is a custom repository.

## Further Notes

- HACS becomes the Marketplace inside Home Assistant with 2026.11 (core PR #183502 is merged). Publishing requirements stay the same: HACS action and Hassfest without errors, `version` and `issue_tracker` in the manifest, `brand/icon.png`. The manifest `version` should match the release tag.
- `guestbook.resident_unlock` has an optional `source` text. It is stored with the resident signal.
- `guestbook.correct_entry` and `guestbook.export` return response data when called with a response: the corrected entry (`entry_id`, `kind`, `decision`, `guests`, `start`, `end`) and the export `path` and `count`.
- `guestbook_visit_ended` carries the end `reason`. `guestbook_visit_corrected` carries the effective `guests`, `certainty`, `start` and `end` next to `entry_id`, `kind` and `guest_name`.
- A `resident` or `delivery` correction closes an open visit at once. Its end reason is `corrected`.
- No arrival push for a visit that starts because a guest phone was already home at startup or when the guest was added (`guest_phone_at_start`). No end push for a visit closed by a correction (`corrected`).
- Removing the integration deletes its stored data.
- The README needs a privacy section: Guestbook stores personal data of third parties (who visited, when, which phone). It explains retention and how to export and delete data.
- Primary sources checked on 2026-10-21: HACS publish docs and action docs, HA brands docs and blog of 2026-02-24, calendar and notify entity docs, Companion app actionable notifications docs, config subentries docs, PyPI metadata of `pytest-homeassistant-custom-component` 0.13.373 (pins HA 2026.10.2, Python ≥ 3.14).
