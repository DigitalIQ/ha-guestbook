# 10: Pushes for arrival, end and unanswered rings

**What to build:** Pushes to the selected targets: Companion app phones (as `mobile_app` devices) and text-only `notify` entities. Each push type can be switched on or off. Arrival and end only when no resident is home.

**Blocked by:** 08

**Status:** ready-for-agent

- [ ] Options flow: phones, notify entities, switches arrival (on), end (on), correction question (on), unanswered ring (off)
- [ ] Phones get `notify.mobile_app_<device>`, notify entities get `notify.send_message`
- [ ] Arrival and end pushes only when no selected resident `person` is `home`
- [ ] Unanswered ring push when switched on
- [ ] Push text in the Home Assistant language, text-only pushes include the entry id
