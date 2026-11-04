from custom_components.guestbook.core.candidates import (
    EntityFacts,
    device_ids_of,
    door_candidates,
    doorbell_candidates,
    fold,
    guest_tracker_candidates,
    lock_candidates,
    presence_candidates,
    resident_candidates,
    resident_signal_candidates,
)


def facts(entity_id: str, **kwargs) -> EntityFacts:
    kwargs.setdefault("name", entity_id.split(".", 1)[1].replace("_", " ").title())
    return EntityFacts(entity_id, **kwargs)


# --- text and areas -------------------------------------------------------------------------------------------


def test_fold_spells_out_umlauts_and_removes_accents():
    assert fold("Haustür") == "haustuer"
    assert fold("Straße Café") == "strasse cafe"


def test_gate_drops_hidden_disabled_config_and_diagnostic_entities():
    items = [
        facts("event.front_doorbell", device_class="doorbell", hidden=True),
        facts("event.side_doorbell", device_class="doorbell", disabled=True),
        facts("event.back_doorbell", device_class="doorbell", entity_category="config"),
        facts("event.cellar_doorbell", device_class="doorbell", entity_category="diagnostic"),
    ]

    assert doorbell_candidates(items).listed == ()


# --- doorbells ------------------------------------------------------------------------------------------------


def test_event_with_the_doorbell_class_is_listed_and_suggested():
    items = [
        facts("event.front_door_ding", device_class="doorbell"),
        facts("event.hall_remote", device_class="button"),
        facts("binary_sensor.kitchen_window"),
    ]

    result = doorbell_candidates(items)

    assert result.listed == ("event.front_door_ding",)
    assert result.suggested == ("event.front_door_ding",)


def test_every_event_with_the_doorbell_class_is_suggested():
    items = [facts("event.front_ding", device_class="doorbell"), facts("event.side_ding", device_class="doorbell")]

    assert doorbell_candidates(items).suggested == ("event.front_ding", "event.side_ding")


def test_binary_sensor_doorbell_without_a_class_is_found_by_name():
    items = [
        facts("binary_sensor.front_visitor"),
        facts("binary_sensor.kitchen_window", device_class="window"),
        facts("binary_sensor.hall_motion", device_class="motion"),
    ]

    result = doorbell_candidates(items)

    assert result.listed == ("binary_sensor.front_visitor",)
    assert result.suggested == ("binary_sensor.front_visitor",)


def test_german_bell_names_are_found():
    items = [
        facts("binary_sensor.haustuer_klingel", name="Haustürklingel"),
        facts("binary_sensor.klingel_taster", name="Türklingel"),
    ]

    assert set(doorbell_candidates(items).listed) == {"binary_sensor.haustuer_klingel", "binary_sensor.klingel_taster"}


def test_motion_sensor_of_a_doorbell_camera_is_listed_but_not_suggested():
    items = [facts("binary_sensor.front_doorbell_motion", device_class="motion")]

    result = doorbell_candidates(items)

    assert result.listed == ("binary_sensor.front_doorbell_motion",)
    assert result.suggested == ()


def test_press_event_on_a_camera_device_is_listed_and_a_plain_button_in_the_hall_too():
    items = [
        facts("event.porch_cam_button", event_types=("press",), device_domains=frozenset({"camera", "event"})),
        facts("event.hall_wall_button", event_types=("press",), areas=("Hallway",)),
        facts("event.kitchen_button", event_types=("press",), areas=("Kitchen",)),
    ]

    result = doorbell_candidates(items)

    assert result.listed == ("event.porch_cam_button", "event.hall_wall_button")
    assert result.suggested == ()


def test_event_with_ring_types_is_listed():
    items = [facts("event.entry_unit", event_types=("ring", "missed"))]

    assert doorbell_candidates(items).listed == ("event.entry_unit",)


def test_class_beats_name_words_for_the_suggestion():
    items = [facts("event.front_ding", device_class="doorbell"), facts("binary_sensor.side_visitor")]

    result = doorbell_candidates(items)

    assert result.listed == ("event.front_ding", "binary_sensor.side_visitor")
    assert result.suggested == ("event.front_ding",)


# --- door contacts --------------------------------------------------------------------------------------------


def test_door_class_is_listed_window_is_not():
    items = [
        facts("binary_sensor.patio_contact", device_class="door"),
        facts("binary_sensor.bedroom_window", device_class="window"),
        facts("binary_sensor.hall_motion", device_class="motion"),
    ]

    assert door_candidates(items).listed == ("binary_sensor.patio_contact",)


def test_opening_class_and_door_named_contacts_without_a_class_are_listed():
    items = [
        facts("binary_sensor.gate_contact", device_class="opening"),
        facts("binary_sensor.haustuer", name="Haustür"),
        facts("binary_sensor.window_sensor", name="Window sensor"),
        facts("binary_sensor.outdoor_motion", name="Outdoor motion"),
    ]

    assert set(door_candidates(items).listed) == {"binary_sensor.gate_contact", "binary_sensor.haustuer"}


def test_a_window_named_after_a_door_is_listed_last():
    items = [
        facts("binary_sensor.door_window", device_class="window", name="Door window"),
        facts("binary_sensor.patio_contact", device_class="door"),
    ]

    assert door_candidates(items).listed == ("binary_sensor.patio_contact", "binary_sensor.door_window")


def test_a_doorbell_binary_sensor_is_not_a_door_contact():
    assert door_candidates([facts("binary_sensor.front_doorbell", name="Front doorbell")]).listed == ()


def test_door_class_in_the_entrance_area_is_suggested():
    items = [
        facts("binary_sensor.entry_contact", device_class="door", areas=("Hallway",)),
        facts("binary_sensor.patio_contact", device_class="door", areas=("Living room",)),
    ]

    result = door_candidates(items)

    assert result.listed == ("binary_sensor.entry_contact", "binary_sensor.patio_contact")
    assert result.suggested == ("binary_sensor.entry_contact",)


def test_area_aliases_and_german_names_count_as_entrance():
    items = [
        facts("binary_sensor.a", device_class="door", areas=("Ground floor", "Eingangsbereich")),
        facts("binary_sensor.b", device_class="door", areas=("Haustür",)),
        facts("binary_sensor.c", device_class="door", areas=("Diele",)),
        facts("binary_sensor.d", device_class="door", areas=("Flur",)),
    ]

    assert set(door_candidates(items).suggested) == {
        "binary_sensor.a",
        "binary_sensor.b",
        "binary_sensor.c",
        "binary_sensor.d",
    }


def test_door_on_the_device_of_a_suggested_lock_is_suggested():
    items = [
        facts("binary_sensor.lock_contact", device_class="door", device_id="lock-1"),
        facts("binary_sensor.patio_contact", device_class="door", device_id="patio-1"),
    ]

    assert door_candidates(items, anchor_devices={"lock-1"}).suggested == ("binary_sensor.lock_contact",)


def test_door_class_with_a_front_door_name_is_suggested_without_an_area():
    items = [
        facts("binary_sensor.front_door", device_class="door"),
        facts("binary_sensor.cellar_contact", device_class="door"),
    ]

    assert door_candidates(items).suggested == ("binary_sensor.front_door",)


# --- presence -------------------------------------------------------------------------------------------------


def test_presence_lists_occupancy_presence_and_motion_only():
    items = [
        facts("binary_sensor.a", device_class="occupancy"),
        facts("binary_sensor.b", device_class="presence"),
        facts("binary_sensor.c", device_class="motion"),
        facts("binary_sensor.d", device_class="door"),
        facts("binary_sensor.e"),
    ]

    assert set(presence_candidates(items).listed) == {"binary_sensor.a", "binary_sensor.b", "binary_sensor.c"}


def test_presence_is_only_suggested_in_the_entrance_area_and_prefers_occupancy_over_motion():
    # An Aqara FP300: occupancy and PIR motion on one device, plus config and diagnostic entities.
    items = [
        facts("binary_sensor.fp300_occupancy", device_class="occupancy", device_id="fp300", areas=("Flur",)),
        facts("binary_sensor.fp300_motion", device_class="motion", device_id="fp300", areas=("Flur",)),
        facts(
            "binary_sensor.fp300_pir",
            device_class="motion",
            device_id="fp300",
            areas=("Flur",),
            entity_category="diagnostic",
        ),
        facts("binary_sensor.fp300_zone_config", device_class="occupancy", device_id="fp300", entity_category="config"),
        facts("binary_sensor.living_presence", device_class="occupancy", areas=("Living room",)),
    ]

    result = presence_candidates(items)

    assert set(result.listed) == {
        "binary_sensor.fp300_occupancy",
        "binary_sensor.fp300_motion",
        "binary_sensor.living_presence",
    }
    assert result.suggested == ("binary_sensor.fp300_occupancy",)


def test_the_shortest_zone_name_is_the_device_wide_suggestion():
    items = [
        facts(
            "binary_sensor.fp2_zone_desk",
            name="FP2 Zone Desk",
            device_class="presence",
            device_id="fp2",
            areas=("Hall",),
        ),
        facts("binary_sensor.fp2", name="FP2", device_class="presence", device_id="fp2", areas=("Hall",)),
    ]

    assert presence_candidates(items).suggested == ("binary_sensor.fp2",)


def test_outdoor_motion_is_listed_after_indoor_and_never_suggested():
    items = [
        facts("binary_sensor.garden_motion", device_class="motion", areas=("Garden entrance",)),
        facts("binary_sensor.living_motion", device_class="motion", areas=("Living room",)),
    ]

    result = presence_candidates(items)

    assert result.listed == ("binary_sensor.living_motion", "binary_sensor.garden_motion")
    assert result.suggested == ()


# --- locks ----------------------------------------------------------------------------------------------------


def test_the_only_lock_is_suggested():
    result = lock_candidates([facts("lock.front"), facts("sensor.not_a_lock")])

    assert result.listed == ("lock.front",)
    assert result.suggested == ("lock.front",)


def test_with_several_locks_the_entrance_one_is_suggested():
    items = [
        facts("lock.cellar"),
        facts("lock.entry", areas=("Eingang",)),
        facts("lock.shed"),
    ]

    result = lock_candidates(items)

    assert result.listed[0] == "lock.entry"
    assert set(result.listed) == {"lock.cellar", "lock.entry", "lock.shed"}
    assert result.suggested == ("lock.entry",)


def test_lock_on_the_device_of_a_suggested_doorbell_is_suggested():
    items = [facts("lock.cellar"), facts("lock.video_lock", device_id="bell-1"), facts("lock.shed")]

    assert lock_candidates(items, doorbell_devices={"bell-1"}).suggested == ("lock.video_lock",)


# --- residents ------------------------------------------------------------------------------------------------


def test_residents_are_all_persons_and_those_with_a_user_are_suggested():
    items = [facts("person.sam", has_user=True), facts("person.visitor"), facts("sensor.x")]

    result = resident_candidates(items)

    assert result.listed == ("person.sam", "person.visitor")
    assert result.suggested == ("person.sam",)


# --- resident signals -----------------------------------------------------------------------------------------


def test_router_and_bluetooth_trackers_of_the_residents_are_suggested_and_gps_is_listed():
    items = [
        facts(
            "person.sam",
            device_trackers=("device_tracker.sam_router", "device_tracker.sam_ble", "device_tracker.sam_gps"),
        ),
        facts("device_tracker.sam_router", source_type="router"),
        facts("device_tracker.sam_ble", source_type="bluetooth_le"),
        facts("device_tracker.sam_gps", source_type="gps"),
        facts("device_tracker.other_phone", source_type="router"),
    ]

    result = resident_signal_candidates(items, persons={"person.sam"}, suggested_persons={"person.sam"})

    assert result.listed == ("device_tracker.sam_ble", "device_tracker.sam_router", "device_tracker.sam_gps")
    assert result.suggested == ("device_tracker.sam_ble", "device_tracker.sam_router")


def test_trackers_of_persons_that_are_not_residents_are_listed_not_suggested():
    items = [
        facts("person.sam", device_trackers=("device_tracker.sam_router",)),
        facts("person.kim", device_trackers=("device_tracker.kim_router",)),
        facts("device_tracker.sam_router", source_type="router"),
        facts("device_tracker.kim_router", source_type="router"),
    ]

    result = resident_signal_candidates(items, persons={"person.sam", "person.kim"}, suggested_persons={"person.sam"})

    assert set(result.listed) == {"device_tracker.sam_router", "device_tracker.kim_router"}
    assert result.suggested == ("device_tracker.sam_router",)


def test_guest_trackers_are_never_resident_signals():
    items = [
        facts("person.sam", device_trackers=("device_tracker.shared",)),
        facts("device_tracker.shared", source_type="router"),
    ]

    result = resident_signal_candidates(
        items, persons={"person.sam"}, suggested_persons={"person.sam"}, guest_trackers={"device_tracker.shared"}
    )

    assert result.listed == ()


def test_fingerprint_entities_are_listed_and_a_temperature_sensor_is_not():
    items = [
        facts("event.fingerprint_reader"),
        facts("sensor.fingerprint_reader", name="Fingerprint reader"),
        facts("binary_sensor.keypad_unlock"),
        facts("sensor.living_temperature", name="Living temperature"),
        facts("switch.coffee_machine"),
        facts("lock.front"),
        facts("input_boolean.resident_home"),
    ]

    result = resident_signal_candidates(items, persons=set())

    assert set(result.listed) == {
        "event.fingerprint_reader",
        "sensor.fingerprint_reader",
        "binary_sensor.keypad_unlock",
        "lock.front",
        "input_boolean.resident_home",
    }
    assert result.suggested == ()


def test_a_device_tracker_that_belongs_to_no_resident_is_not_a_signal():
    assert resident_signal_candidates([facts("device_tracker.nas", source_type="router")], persons=set()).listed == ()


# --- guest trackers -------------------------------------------------------------------------------------------


def test_guest_trackers_exclude_resident_and_taken_and_companion_app_trackers():
    items = [
        facts("person.sam", device_trackers=("device_tracker.sam_router",)),
        facts("device_tracker.sam_router", source_type="router"),
        facts("device_tracker.sam_app", source_type="gps", platform="mobile_app"),
        facts("device_tracker.alex_phone", source_type="router", name="Alex iPhone"),
        facts("device_tracker.robin_phone", source_type="router", name="Robin Pixel"),
    ]

    result = guest_tracker_candidates(items, excluded={"device_tracker.robin_phone"})

    assert result.listed == ("device_tracker.alex_phone",)


def test_phones_rank_above_unnamed_trackers_and_infrastructure_is_dropped():
    items = [
        facts("device_tracker.fritz_a1", name="FRITZ A1", source_type="router"),
        facts("device_tracker.alex_iphone", name="Alex iPhone", source_type="router"),
        facts("device_tracker.living_room_tv", name="Living room TV", source_type="router"),
        facts("device_tracker.printer", name="Office printer", source_type="router"),
        facts("device_tracker.irk_phone", name="Alex watch", source_type="bluetooth_le", platform="private_ble_device"),
    ]

    result = guest_tracker_candidates(items)

    assert result.listed == (
        "device_tracker.alex_iphone",
        "device_tracker.irk_phone",
        "device_tracker.fritz_a1",
    )


def test_tracker_without_a_source_type_is_listed_below_router_trackers():
    items = [facts("device_tracker.plain"), facts("device_tracker.lan", source_type="router")]

    assert guest_tracker_candidates(items).listed == ("device_tracker.lan", "device_tracker.plain")


def test_device_ids_of_returns_the_devices_of_the_entities():
    items = [facts("lock.a", device_id="d1"), facts("lock.b"), facts("lock.c", device_id="d3")]

    assert device_ids_of(items, ["lock.a", "lock.b"]) == {"d1"}
