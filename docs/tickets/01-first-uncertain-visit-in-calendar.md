# 01: First uncertain visit shows up in the visits calendar

**What to build:** The tracer bullet through every layer. A user installs Guestbook, sets it up with one doorbell and one door contact, and sees an uncertain visit in the "Visits" calendar after a ring followed by a door opening. Includes the test setup, the pure rule core with its first rule, the store, the config flow (doorbells, door contacts, presence sensors, residents), the signal adapter and a read-only visits calendar. The visit stays open (end = now) until ticket 02.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] Test setup with `pytest-homeassistant-custom-component` on Python 3.14, ruff, and a GitHub Actions test workflow
- [x] Rule core: ring then door opening or presence within the ring window gives an uncertain visit with reason `ring_then_door` or `ring_then_presence`; door or presence without a ring gives nothing
- [x] Rule core reports its next deadline and never reads the clock
- [x] Config flow creates one entry (single instance) with doorbell (`event` and `binary_sensor`), door, presence and resident selections
- [x] Store saves entries and loads them after a restart
- [x] Calendar "Visits" returns the visit through the calendar API, title "Visit (uncertain)", end = now while open
- [x] Integration test: set fake entity states, read the calendar, see the visit
