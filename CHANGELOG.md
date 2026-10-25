# Changelog

## 0.1.3

Review fixes ahead of the HACS submission.

- The push no longer reads the config entry of the Companion app. The notify service name and the platform (Apple means iOS, anything else Android) come from the device registry only.
- `guestbook.export` can only be called by admin users.
- The test requirements pin `ruff`, and a test pins the recorder history call.

## 0.1.2

Correct entries from the Home Assistant UI.

- `guestbook.correct_entry` and `guestbook.add_note` work without `entry_id`. They then act on the latest entry: the most recent visit or unanswered ring, open or closed. Without such an entry they raise a translated error.
- New sensor "Latest entry" (`sensor.guestbook_latest_entry`) that shows which entry that is.
- New text entity "Guest name" and four buttons "That was me", "Delivery", "Don't know" and "Visit". A press corrects the latest entry with the correction source `button`. "Visit" uses the guest name and clears it after a successful press.
- New push option "Open dashboard path": a tap on a push to a Companion app phone opens that dashboard (`url` for iOS, `clickAction` for Android).
- The correction question on iOS ends with "Press and hold to answer.", because iOS shows the buttons only on a long press.
- The README has an example dashboard with the buttons.

## 0.1.1

Fixes from a code review.

- Security: the buttons of the correction question carry a random one-time token. An answer counts only with the token of the pending question, and only once.
- A guest with two phones at home at startup is recorded with both phones. The visit ends only when all phones are away.
- The per-guest sensor goes off when that guest left a visit that goes on with another guest.
- A renamed guest who returns within the phone grace period is listed once, with the new name.
- A door opening exactly at the end of the ring window counts, even when the timer fires first.
- An entry keeps at most 1000 signals. The oldest door, presence and lock signals are dropped and counted (`dropped_signals`).
- A stored pending ring without a usable deadline no longer blocks the setup. The entry is skipped with a warning.
- Export files are created exclusively and never overwritten.
- Guest names are cut to 64 characters, and the current visit sensor stays below 255 characters.
- `guestbook.add_visit` checks that every guest is a non-empty string.
- A retention purge removes guest suggestions whose visit is gone.
- GitHub Actions are pinned to commit SHAs, and Dependabot updates them weekly.

## 0.1.0

First release.

- Visits from doorbell, door, presence and lock signals, and from guest phones.
- Resident arrivals and unanswered rings.
- Visits and Rings calendars with the full log in the description.
- Sensors, bus events, pushes with a correction question, repair issues and a JSONL export.
- Actions to correct entries, add visits and notes, and export.
