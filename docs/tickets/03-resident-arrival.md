# 03: Resident arrival is never a visit

**What to build:** A ring with a resident signal close to it is stored as a resident arrival and shown nowhere. Resident signals come from selected entities or from the `guestbook.resident_unlock` action.

**Blocked by:** 01

**Status:** ready-for-agent

- [x] Rule core: resident signal from the resident window before the ring until the end of the ring window gives `resident_arrival` (reason `resident_signal`)
- [x] Signal adapter: resident entities fire on a change to `on`, `home`, `unlocked` or a new `event` timestamp
- [x] Action `guestbook.resident_unlock` (optional `source` text) creates a resident signal
- [x] Resident arrivals are stored but appear in no calendar
- [x] Lock entities can be selected; their changes are stored as signals of the entry
