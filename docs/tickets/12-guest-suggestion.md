# 12: Guest suggestion from corrections

**What to build:** When a correction names a guest that has no profile, a repair issue offers to create the guest, with unlinked phones that were home during that visit preselected.

**Blocked by:** 05, 11

**Status:** ready-for-agent

- [ ] Repair issue per unknown guest name, fixable
- [ ] Fix flow creates the guest subentry with name and selected trackers
- [ ] Preselection: `device_tracker` entities that were `home` during the visit and are not linked to a guest
- [ ] Issue disappears when the guest exists
