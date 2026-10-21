# 08: Bus events

**What to build:** Automations can react to the visit lifecycle through bus events.

**Blocked by:** 05

**Status:** ready-for-agent

- [x] `guestbook_visit_started` with `entry_id`, `guests`, `certainty`, `start`
- [x] `guestbook_visit_event` for each signal added to an open visit, with signal kind and source entity id
- [x] `guestbook_visit_ended` with `entry_id`, `guests`, `start`, `end`, `duration`
- [x] No events for resident arrivals; unanswered rings fire none in version 1
