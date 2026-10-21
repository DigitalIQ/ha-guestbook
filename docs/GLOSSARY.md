# Glossary

Terms used in code, tests, tickets and the UI. Use these words, not synonyms.

| Term | Meaning |
| --- | --- |
| **Signal** | One raw input from a source entity, with a kind and a timestamp: ring, door open, door close, presence on, presence off, lock change, guest phone home, guest phone away, resident signal. |
| **Source** | An entity the user selected as input: doorbell, door contact, presence sensor, lock, resident signal. Guest phones are traits, not sources. |
| **Resident** | Someone who lives in the home. Selected as `person` entities. Residents never become visits. |
| **Resident signal** | A signal that proves a resident is arriving or opening the door, e.g. a fingerprint unlock or a resident phone joining the Wi-Fi. Comes from selected entities or from the `resident_unlock` action. |
| **Guest** | A known visitor profile, created in the UI as a config subentry. Has a name and traits. |
| **Trait** | Something that identifies a guest. In version 1: a `device_tracker` (guest phone in the Wi-Fi). |
| **Visit** | One stay of one or more people, from arrival to departure. Has guests, a certainty, signals, a decision, a reason and an optional correction. |
| **Certainty** | `certain` (started by a guest phone) or `uncertain` (started by ring plus door or presence, no phone). |
| **Ring** | A doorbell press. |
| **Ring window** | Time after a ring in which a door opening or presence turns the ring into a visit. |
| **Unanswered ring** | A ring with no door opening or presence in the ring window. Shown in the rings calendar and the export, not in the visits calendar. |
| **Entry** | One stored record: a visit, an unanswered ring or a dismissed resident arrival. |
| **Decision** | What the rule core concluded for an entry: `visit`, `unanswered_ring`, `resident_arrival`. |
| **Reason** | A short machine-readable code plus readable text that says which rule fired, e.g. `ring_then_door`. |
| **Correction** | A user answer that overrides the decision: `resident`, `delivery`, `visit` (with guest name), `unknown`. Stored next to the decision, never replacing it. |
| **Rule core** | The pure Python part that turns signals and settings into entries. Has no Home Assistant imports. |
| **Settings** | The adjustable numbers of the rule core (windows, quiet time, max duration, retention). |
