"""Constants for Guestbook."""

from datetime import timedelta

DOMAIN = "guestbook"

CONF_DOORBELLS = "doorbells"
CONF_DOORS = "doors"
CONF_PRESENCE = "presence"
CONF_LOCKS = "locks"
CONF_RESIDENTS = "residents"
CONF_RESIDENT_SIGNALS = "resident_signals"

ATTR_SOURCE = "source"
SERVICE_RESIDENT_UNLOCK = "resident_unlock"

STORAGE_KEY = "guestbook.entries"
STORAGE_VERSION = 1
SAVE_DELAY = timedelta(seconds=5)

EVENT_VISIT_STARTED = "guestbook_visit_started"
EVENT_VISIT_EVENT = "guestbook_visit_event"
EVENT_VISIT_ENDED = "guestbook_visit_ended"
EVENT_VISIT_CORRECTED = "guestbook_visit_corrected"
