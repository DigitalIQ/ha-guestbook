# 11: Correction question with buttons

**What to build:** For every uncertain visit the phones get a correction question with buttons. The answer is saved as a correction to that visit.

**Blocked by:** 09, 10

**Status:** ready-for-agent

- [ ] Sent at the start of each uncertain visit, also when a resident is home
- [ ] Buttons "That was me", "Delivery", "Visit" (text input for the name), "Don't know"; Android phones get the first three only
- [ ] Action ids contain the entry id, so answers find the right visit
- [ ] `mobile_app_notification_action` with a matching action id saves the correction (source `push`)
- [ ] Answers for unknown or deleted entries are ignored without errors
