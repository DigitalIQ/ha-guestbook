# 14: Settings and repairs

**What to build:** The user tunes all rule numbers in the options flow and changes sources without losing data. Missing source entities raise a repair issue.

**Blocked by:** 02, 03, 05

**Status:** ready-for-agent

- [x] Options flow: ring window, resident window, quiet period, grace period, maximum duration, with defaults from the spec
- [x] Changing sources or settings keeps all stored entries and open visits
- [x] Repair issue per missing source entity, removed when it is back or deselected
- [x] One unavailable source does not stop the others
