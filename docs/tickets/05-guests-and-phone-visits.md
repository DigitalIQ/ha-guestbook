# 05: Guests and certain visits by phone

**What to build:** The user adds guests as config subentries with a name and phones (`device_tracker`). A guest phone joining the Wi-Fi starts a certain visit with the guest's name in the title. The visit ends when all its guest phones have been away for the grace period.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Subentry flow `guest` with `user` and `reconfigure` steps (name, device trackers)
- [ ] Rule core: phone home starts a certain visit (reason `guest_phone`); phone away for the grace period ends it at the moment it went away
- [ ] Rule core: a second guest phone joins the open certain visit
- [ ] Rule core: a guest phone joining an open uncertain visit makes it certain and adds the guest
- [ ] Calendar title lists the guest names
- [ ] Adding, editing and removing guests works without restarting Home Assistant
