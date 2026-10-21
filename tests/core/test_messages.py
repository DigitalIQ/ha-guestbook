from custom_components.guestbook.core import (
    PushKind,
    action_id,
    correction_actions,
    parse_action_id,
    push_message,
    push_title,
)


def test_arrival_names_the_guests_in_english_and_german():
    assert push_title(PushKind.ARRIVAL, "en") == "Visit"
    assert push_message(PushKind.ARRIVAL, "en", ["Alex", "Sam"]) == "Arrived: Alex, Sam."
    assert push_title(PushKind.ARRIVAL, "de") == "Besuch"
    assert push_message(PushKind.ARRIVAL, "de", ["Alex"]) == "Angekommen: Alex."


def test_arrival_without_guests_says_someone_arrived():
    assert push_message(PushKind.ARRIVAL, "en", []) == "Someone arrived."
    assert push_message(PushKind.ARRIVAL, "de", []) == "Jemand ist angekommen."


def test_end_and_unanswered_ring_texts():
    assert push_title(PushKind.END, "en") == "Visit ended"
    assert push_message(PushKind.END, "en", ["Alex"]) == "Left: Alex."
    assert push_message(PushKind.END, "de", []) == "Der Besuch ist vorbei."
    assert push_title(PushKind.UNANSWERED_RING, "de") == "Klingel ohne Antwort"
    assert push_message(PushKind.UNANSWERED_RING, "en", []).startswith("Someone rang")


def test_text_only_messages_carry_the_entry_id():
    assert push_message(PushKind.ARRIVAL, "en", ["Alex"], entry_id="abc123") == "Arrived: Alex. Entry id: abc123"
    assert push_message(PushKind.ARRIVAL, "de", [], entry_id="abc123") == "Jemand ist angekommen. Eintrags-ID: abc123"


def test_correction_text_only_mentions_the_action():
    message = push_message(PushKind.CORRECTION, "en", [], entry_id="abc123")
    assert "abc123" in message
    assert "guestbook.correct_entry" in message
    assert "guestbook.correct_entry" in push_message(PushKind.CORRECTION, "de", [], entry_id="abc123")


def test_correction_for_a_phone_has_no_action_hint():
    assert "guestbook.correct_entry" not in push_message(PushKind.CORRECTION, "en", [])


def test_unknown_language_falls_back_to_english_and_region_is_ignored():
    assert push_title(PushKind.END, "fr") == "Visit ended"
    assert push_title(PushKind.END, "de-AT") == "Besuch beendet"


def test_correction_actions_carry_the_entry_id():
    actions = correction_actions("en", "abc123")

    assert [a["action"] for a in actions] == [
        "GUESTBOOK_RESIDENT_abc123",
        "GUESTBOOK_DELIVERY_abc123",
        "GUESTBOOK_VISIT_abc123",
        "GUESTBOOK_UNKNOWN_abc123",
    ]
    assert [a["title"] for a in actions] == ["That was me", "Delivery", "Visit", "Don't know"]
    visit = actions[2]
    assert visit["behavior"] == "textInput"
    assert visit["textInputButtonTitle"] == "Save"
    assert visit["textInputPlaceholder"] == "Name of the guest"
    assert all("behavior" not in a for a in actions if a is not visit)


def test_correction_actions_are_translated():
    actions = correction_actions("de", "abc123")

    assert [a["title"] for a in actions] == ["War ich", "Lieferung", "Besuch", "Weiß nicht"]
    assert actions[2]["textInputPlaceholder"] == "Name des Gastes"


def test_android_gets_the_first_three_actions_only():
    actions = correction_actions("en", "abc123", android=True)

    assert [a["title"] for a in actions] == ["That was me", "Delivery", "Visit"]


def test_action_ids_round_trip():
    assert action_id("visit", "abc123") == "GUESTBOOK_VISIT_abc123"
    assert parse_action_id("GUESTBOOK_VISIT_abc123") == ("visit", "abc123")
    assert parse_action_id("GUESTBOOK_UNKNOWN_abc123") == ("unknown", "abc123")


def test_foreign_or_malformed_action_ids_do_not_parse():
    for action in (
        "ALARM",
        "URI",
        "REPLY",
        "GUESTBOOK_",
        "GUESTBOOK_VISIT_",
        "GUESTBOOK_COFFEE_abc123",
        "guestbook_visit_abc",
    ):
        assert parse_action_id(action) is None
