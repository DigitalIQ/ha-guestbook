"""Constants for Guestbook."""

from datetime import timedelta

DOMAIN = "guestbook"

CONF_DOORBELLS = "doorbells"
CONF_DOORS = "doors"
CONF_PRESENCE = "presence"
CONF_LOCKS = "locks"
CONF_RESIDENTS = "residents"
CONF_RESIDENT_SIGNALS = "resident_signals"
SOURCE_KEYS = (CONF_DOORBELLS, CONF_DOORS, CONF_PRESENCE, CONF_LOCKS, CONF_RESIDENTS, CONF_RESIDENT_SIGNALS)
CONF_NAME = "name"
CONF_TRACKERS = "trackers"

CONF_PHONES = "phones"
CONF_NOTIFY_ENTITIES = "notify_entities"
CONF_PUSH_ARRIVAL = "push_arrival"
CONF_PUSH_END = "push_end"
CONF_PUSH_CORRECTION = "push_correction"
CONF_PUSH_UNANSWERED_RING = "push_unanswered_ring"
CONF_PUSH_OPEN_PATH = "push_open_path"
PUSH_DEFAULTS = {
    CONF_PUSH_ARRIVAL: True,
    CONF_PUSH_END: True,
    CONF_PUSH_CORRECTION: True,
    CONF_PUSH_UNANSWERED_RING: False,
}

CONF_RING_WINDOW = "ring_window"
CONF_RESIDENT_WINDOW = "resident_window"
CONF_QUIET_PERIOD = "quiet_period"
CONF_ENTRY_GRACE = "entry_grace"
CONF_PHONE_GRACE = "phone_grace"
CONF_MAX_DURATION = "max_duration"
CONF_RETENTION = "retention"

SUBENTRY_GUEST = "guest"

ATTR_SOURCE = "source"
SERVICE_RESIDENT_UNLOCK = "resident_unlock"
SERVICE_CORRECT_ENTRY = "correct_entry"
SERVICE_ADD_VISIT = "add_visit"
SERVICE_ADD_NOTE = "add_note"
SERVICE_EXPORT = "export"
ATTR_ENTRY_ID = "entry_id"
ATTR_KIND = "kind"
ATTR_GUEST_NAME = "guest_name"
ATTR_GUESTS = "guests"
ATTR_START = "start"
ATTR_END = "end"
ATTR_NOTE = "note"
EXPORT_DIR = "guestbook"
PURGE_INTERVAL = timedelta(days=1)
SOURCE_ACTION = "action"
SOURCE_PUSH = "push"
SOURCE_BUTTON = "button"
MAX_GUEST_NAME_INPUT = 64  # the maximum of the guest name text entity, the same as MAX_GUEST_NAME of the core
QUESTION_TOKEN_BYTES = 8  # random bytes of the one-time token in a correction button (11 characters)

STORAGE_KEY = "guestbook.entries"
STORAGE_VERSION = 1
SAVE_DELAY = timedelta(seconds=5)

EVENT_VISIT_STARTED = "guestbook_visit_started"
EVENT_VISIT_EVENT = "guestbook_visit_event"
EVENT_VISIT_ENDED = "guestbook_visit_ended"
EVENT_VISIT_CORRECTED = "guestbook_visit_corrected"
