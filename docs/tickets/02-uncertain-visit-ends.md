# 02: Uncertain visit ends

**What to build:** An uncertain visit ends at the first door opening that is followed by the quiet period, or after the maximum duration. Open visits survive a restart and still end correctly.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Rule core: end at the door opening followed by the quiet period (reason `door_then_quiet`); door openings in the first 2 minutes do not count
- [ ] Rule core: a second door opening inside the quiet period moves the end candidate
- [ ] Rule core: end at start plus maximum duration (reason `max_duration`)
- [ ] Integration: timers follow the rule core's next deadline
- [ ] Integration: a visit open during a restart is rebuilt and ends correctly
- [ ] Calendar shows the real end time
