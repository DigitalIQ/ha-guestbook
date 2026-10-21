# 09: Corrections and additions by action

**What to build:** The user fixes and adds entries with actions. Calendars, sensors and the store follow at once. The original decision stays next to the correction.

**Blocked by:** 04, 08

**Status:** ready-for-agent

- [x] `guestbook.correct_entry` with entry id, kind (`resident`, `delivery`, `visit`, `unknown`), optional guest name, start, end, note
- [x] `resident` removes the entry from all calendars; `delivery` moves it to the rings calendar; `visit` moves an unanswered ring to the visits calendar
- [x] `guestbook.add_visit` with guests, start, end, note
- [x] `guestbook.add_note` adds a note to an entry
- [x] `guestbook_visit_corrected` bus event
- [x] Errors for unknown entry ids are readable and translated
