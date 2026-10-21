# 06: Visit sensors

**What to build:** Entities for automations: binary sensor "Visit active", sensor "Current visit", one binary sensor per guest.

**Blocked by:** 05

**Status:** ready-for-agent

- [ ] Binary sensor "Visit active" is on while any visit is open
- [ ] Sensor "Current visit": state lists guest names or "unknown", attributes `entry_id`, `start`, `certainty`; small attributes only
- [ ] One binary sensor per guest, on while that guest is in an open visit; created and removed with the guest
- [ ] States are right again after a restart with an open visit
