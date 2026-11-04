# 17: Detect fitting entities in the setup

**What to build:** The setup and options forms list only entities that fit each field, preselect the likely ones at setup and keep an escape hatch to every entity.

**Blocked by:** 14, 12

**Status:** ready-for-agent

- [x] Rule core `core/candidates.py` ranks doorbells, door contacts, presence sensors, locks, residents, resident signals and guest phones from `EntityFacts` (device class first, English and German name words as fallback, area and shared device as bonus); no Home Assistant imports
- [x] `discovery.py` reads the entity, device and area registries and the states; hidden, disabled, config and diagnostic entities are never offered; the area falls back from entity to device to parent device
- [x] Doorbells as `binary_sensor` without a device class, an Aqara FP300 (occupancy plus motion), Fritz!Box router trackers and `private_ble_device` trackers are handled; a doorbell is never a door contact
- [x] Guest phones exclude persons' trackers, other guests' trackers, resident signal trackers and Companion app trackers (guest form and repair fix flow)
- [x] Setup is two steps (sources, then residents and signals) and preselects the likely entities; the options steps preselect nothing, except push phones that were never saved
- [x] Every entity step has a collapsed Advanced section with "Show all entities"; one submit shows the step again with unfiltered lists and keeps the values; the next submit saves without the `advanced` key
- [x] Stored values always stay selectable, so existing setups never fail validation; a field with no candidates falls back to the old selector and says so
- [x] `strings.json`, `en` and `de` translations, README, spec, architecture and glossary updated
- [x] Full test suite green
