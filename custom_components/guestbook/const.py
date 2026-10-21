"""Constants for Guestbook."""

from datetime import timedelta

DOMAIN = "guestbook"

CONF_DOORBELLS = "doorbells"
CONF_DOORS = "doors"
CONF_PRESENCE = "presence"
CONF_LOCKS = "locks"
CONF_RESIDENTS = "residents"
CONF_RESIDENT_SIGNALS = "resident_signals"
CONF_NAME = "name"
CONF_TRACKERS = "trackers"

SUBENTRY_GUEST = "guest"

ATTR_SOURCE = "source"
SERVICE_RESIDENT_UNLOCK = "resident_unlock"
SERVICE_CORRECT_ENTRY = "correct_entry"
SERVICE_ADD_VISIT = "add_visit"
SERVICE_ADD_NOTE = "add_note"
ATTR_ENTRY_ID = "entry_id"
ATTR_KIND = "kind"
ATTR_GUEST_NAME = "guest_name"
ATTR_GUESTS = "guests"
ATTR_START = "start"
ATTR_END = "end"
ATTR_NOTE = "note"
CORRECTION_KINDS = ("resident", "delivery", "visit", "unknown")
SOURCE_ACTION = "action"
SOURCE_PUSH = "push"

STORAGE_KEY = "guestbook.entries"
STORAGE_VERSION = 1
SAVE_DELAY = timedelta(seconds=5)

EVENT_VISIT_STARTED = "guestbook_visit_started"
EVENT_VISIT_EVENT = "guestbook_visit_event"
EVENT_VISIT_ENDED = "guestbook_visit_ended"
EVENT_VISIT_CORRECTED = "guestbook_visit_corrected"
