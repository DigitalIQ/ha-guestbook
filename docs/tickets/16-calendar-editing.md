# 16: Edit entries in the calendar

**What to build:** The user taps an event in the Home Assistant calendar, edits it in the dialog and the edit becomes a correction.

**Blocked by:** 09

**Status:** ready-for-agent

- [x] Both calendars support `UPDATE_EVENT` and `DELETE_EVENT`; every event has the entry id as `uid`
- [x] The title is read like a correction answer (English and German, case-insensitive, `Visit: <name>` or a bare name); an unchanged title changes nothing
- [x] Changed start and end become the display overrides (whole minutes); the end of a running visit is ignored; end before start is refused
- [x] Added description lines become notes; the log stays generated
- [x] Delete hides the entry (correction `resident`, source `calendar`) and keeps it in the storage and the export
- [x] Pending rings, unknown ids, entries of the other calendar, all-day and repeating events and empty titles fail with a translated message
- [x] README, spec, architecture, glossary and changelog updated; `en` and `de` translations complete
