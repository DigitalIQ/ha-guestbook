# 13: JSONL export and retention

**What to build:** The user exports entries as JSONL for tuning, and old entries are deleted after the retention period.

**Blocked by:** 09

**Status:** ready-for-agent

- [x] `guestbook.export` writes `/config/guestbook/guestbook-<timestamp>.jsonl`, one entry per line, with signals, decision, reason, correction, notes and settings snapshot
- [x] Optional `start` and `end` limit the range
- [x] Action returns the file path as response data
- [x] Retention setting (default 365 days) in the options; purge at startup and once a day
