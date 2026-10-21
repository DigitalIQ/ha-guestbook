# 04: Unanswered rings go to the rings calendar

**What to build:** A ring with no door opening, presence or resident signal in the ring window is an unanswered ring. A second calendar "Rings" shows unanswered rings (and later deliveries).

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] Rule core: ring window expires with nothing gives `unanswered_ring` (reason `ring_no_entry`)
- [ ] Calendar "Rings" with one short event per unanswered ring
- [ ] Unanswered rings never show in the visits calendar
