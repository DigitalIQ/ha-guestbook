"""End-to-end scenarios for Guestbook against the dev HA. Real waits: the rules run on 1 minute windows.

Usage: .venv/bin/python dev/scenarios.py [1 2 3 ...]     (default: all; takes about 12 minutes)
Needs dev/setup_guestbook.py to have run. Prints a PASS/FAIL table and writes .tmp/scenario-results.json.
Nothing secret is printed: webhook ids stay in dev/.env.
"""

import asyncio
import json
import subprocess
import sys
import time
import traceback
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiohttp

import ws

ROOT = Path(__file__).resolve().parent.parent
HEADERS = {"Authorization": f"Bearer {ws.ENV['HA_TOKEN']}"}
IOS, ANDROID = ws.ENV["GB_IOS_WEBHOOK"], ws.ENV["GB_ANDROID_WEBHOOK"]
VISITS, RINGS = "calendar.guestbook_visits", "calendar.guestbook_rings"
GUEST, RESIDENT = "device_tracker.demo_alex_phone", "device_tracker.demo_resident_phone"
WINDOW = 60  # every rule is one minute
EVENT_TYPES = ["guestbook_visit_started", "guestbook_visit_event", "guestbook_visit_ended",
               "guestbook_visit_corrected", "mobile_app_notification_action"]


def now() -> datetime:
    return datetime.now(UTC)


class Harness:
    def __init__(self):
        self.http: aiohttp.ClientSession | None = None
        self.client: ws.Client | None = None
        self.events: list[tuple[datetime, str, dict]] = []
        self.pushes: dict[str, list[tuple[datetime, dict]]] = {IOS: [], ANDROID: []}
        self.last_resident_signal = datetime.min.replace(tzinfo=UTC)
        self.checks: list[tuple[bool, str, str]] = []

    async def connect(self):
        self.http = self.http or aiohttp.ClientSession()
        self.client = await ws.connect(self.http)
        for event_type in EVENT_TYPES:
            await self.client.subscribe(
                {"type": "subscribe_events", "event_type": event_type},
                lambda ev: self.events.append((now(), ev["event_type"], ev["data"])),
            )
        for webhook in (IOS, ANDROID):
            await self.client.subscribe(
                {"type": "mobile_app/push_notification_channel", "webhook_id": webhook},
                lambda data, webhook=webhook: self.pushes[webhook].append((now(), data)),
            )

    async def rest(self, method, path, body=None, ok_empty=False):
        async with self.http.request(method, ws.URL + path, json=body, headers=HEADERS) as res:
            if res.status >= 400:
                raise RuntimeError(f"{method} {path}: {res.status} {(await res.text())[:300]}")
            return await res.json() if res.content_type == "application/json" else None

    async def state(self, entity_id):
        return await self.rest("GET", f"/api/states/{entity_id}")

    async def toggle(self, name, on):
        await self.rest("POST", f"/api/services/input_boolean/turn_{'on' if on else 'off'}",
                        {"entity_id": f"input_boolean.{name}"})
        if name == "demo_fingerprint" and on:
            self.last_resident_signal = now()

    async def tap(self, name, seconds=1):
        await self.toggle(name, True)
        await asyncio.sleep(seconds)
        await self.toggle(name, False)

    async def set_tracker(self, entity_id, state):
        await self.rest("POST", f"/api/states/{entity_id}", {"state": state, "attributes": {"source_type": "router"}})

    async def calendar(self, entity_id, since: datetime):
        start = (since - timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        end = (now() + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        rows = await self.rest("GET", f"/api/calendars/{entity_id}?start={start}&end={end}")
        out = []
        for row in rows:
            begin = datetime.fromisoformat(row["start"]["dateTime"] if isinstance(row["start"], dict) else row["start"])
            finish = datetime.fromisoformat(row["end"]["dateTime"] if isinstance(row["end"], dict) else row["end"])
            if begin >= since - timedelta(seconds=5):
                out.append({**row, "start_dt": begin, "end_dt": finish})
        return out

    def evs(self, event_type, since, **match):
        return [d for t, e, d in self.events
                if e == event_type and t >= since and all(d.get(k) == v for k, v in match.items())]

    def push_list(self, webhook, since):
        return [d for t, d in self.pushes[webhook] if t >= since]

    async def until(self, cond, timeout=20, what=""):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            result = cond()
            if asyncio.iscoroutine(result):
                result = await result
            if result:
                return result
            await asyncio.sleep(0.5)
        return None

    def check(self, ok, name, detail=""):
        self.checks.append((bool(ok), name, str(detail)[:300]))
        print(("  ok   " if ok else "  FAIL ") + name + (f"  [{str(detail)[:200]}]" if not ok and detail else ""), flush=True)
        return bool(ok)

    async def reset(self):
        """Quiet start: sources off, phones away, no open visit, resident signal memory expired."""
        for name in ("demo_doorbell", "demo_front_door", "demo_hallway", "demo_fingerprint"):
            await self.toggle(name, False)
        await self.toggle("demo_lock_open", False)
        await self.set_tracker(GUEST, "not_home")
        await self.set_tracker(RESIDENT, "not_home")
        await self.until(lambda: self._is("person.demo_resident", "not_home"), 10)
        wait = WINDOW + 3 - (now() - self.last_resident_signal).total_seconds()
        if wait > 0:
            print(f"  (waiting {wait:.0f}s for the resident window to expire)", flush=True)
            await asyncio.sleep(wait)
        active = await self.state("binary_sensor.guestbook_visit_active")
        if active["state"] == "on":
            print("  (a visit is still open from before; waiting for it)", flush=True)
            await self.until(lambda: self._is("binary_sensor.guestbook_visit_active", "off"), WINDOW * 2)

    async def _is(self, entity_id, value):
        return (await self.state(entity_id))["state"] == value

    async def answer(self, webhook_push, kind, since, reply_text=None):
        """Press a button of a captured push: fire the Companion app action event with the real action id."""
        actions = webhook_push["data"]["actions"]
        action = next(a for a in actions if a["action"].startswith(f"GUESTBOOK_{kind}_"))
        body = {"action": action["action"]}
        if reply_text is not None:
            body["reply_text"] = reply_text
        await self.rest("POST", "/api/events/mobile_app_notification_action", body)
        return action


# --- scenarios ---------------------------------------------------------------------------------------------


async def s1_ring_door_delivery(h: Harness):
    """Ring + door -> uncertain visit, correction question push, answer Delivery -> rings calendar."""
    t0 = now()
    await h.tap("demo_doorbell")
    await asyncio.sleep(3)
    await h.toggle("demo_front_door", True)
    started = await h.until(lambda: h.evs("guestbook_visit_started", t0), 10)
    h.check(started, "visit_started event")
    started = (started or [{}])[0]
    h.check(started.get("certainty") == "uncertain", "certainty uncertain", started)
    entry_id = started.get("entry_id")
    cur = await h.state("sensor.guestbook_current_visit")
    h.check(cur["state"] == "Unknown guest" and cur["attributes"].get("entry_id") == entry_id, "current visit sensor", cur)
    h.check((await h.state("binary_sensor.guestbook_visit_active"))["state"] == "on", "visit_active on")
    visits = await h.calendar(VISITS, t0)
    h.check(len(visits) == 1 and visits[0]["summary"] == "Visit (uncertain)", "visits calendar has the uncertain visit", visits and visits[0]["summary"])
    h.check(visits and "ring" in (visits[0].get("description") or "").lower(), "description mentions ring", visits and visits[0].get("description"))

    # pushes: arrival + correction question on both phones
    await h.until(lambda: len(h.push_list(IOS, t0)) >= 2 and len(h.push_list(ANDROID, t0)) >= 2, 10)
    ios, android = h.push_list(IOS, t0), h.push_list(ANDROID, t0)
    h.check(len(ios) == 2 and len(android) == 2, "two pushes per phone (arrival + question)", (len(ios), len(android)))
    question = next((p for p in ios if p.get("data", {}).get("actions")), None)
    h.check(question is not None, "iOS question push carries data.actions")
    if question:
        ids = [a["action"] for a in question["data"]["actions"]]
        tokens = {i.rsplit(entry_id + "_", 1)[-1] for i in ids}
        h.check(len(ids) == 4 and all(f"_{entry_id}_" in i for i in ids) and len(tokens) == 1 and "" not in tokens,
                "iOS has 4 buttons for this entry, all with the same token", ids)
        h.check(question["data"].get("tag") == entry_id, "tag is the entry id")
        visit_btn = next(a for a in question["data"]["actions"] if a["action"].startswith("GUESTBOOK_VISIT_"))
        h.check(visit_btn.get("behavior") == "textInput", "VISIT button asks for text", visit_btn)
    aq = next((p for p in android if p.get("data", {}).get("actions")), None)
    h.check(aq is not None and len(aq["data"]["actions"]) == 3, "Android gets 3 buttons", aq and len(aq["data"]["actions"]))
    h.check(any(p.get("title") == "Visit" for p in ios), "arrival push title", [p.get("title") for p in ios])

    # an answer with a wrong token is ignored, the real one counts
    t1 = now()
    await h.rest("POST", "/api/events/mobile_app_notification_action", {"action": f"GUESTBOOK_RESIDENT_{entry_id}_wrongtoken"})
    await asyncio.sleep(2)
    h.check(not h.evs("guestbook_visit_corrected", t1), "answer with a wrong token is ignored")
    h.check((await h.state("binary_sensor.guestbook_visit_active"))["state"] == "on", "visit still open after the wrong token")

    # answer Delivery
    t1 = now()
    await h.answer(question, "DELIVERY", t1)
    corrected = await h.until(lambda: h.evs("guestbook_visit_corrected", t1), 10)
    h.check(corrected and corrected[0]["kind"] == "delivery" and corrected[0]["entry_id"] == entry_id, "corrected event kind delivery", corrected)
    await asyncio.sleep(1)
    h.check(not await h.calendar(VISITS, t0), "entry left the visits calendar")
    rings = await h.calendar(RINGS, t0)
    h.check(len(rings) == 1 and rings[0].get("summary") in ("Delivery", "Lieferung"), "entry is in rings calendar as Delivery", rings and rings[0].get("summary"))
    h.check(h.evs("guestbook_visit_ended", t1, reason="corrected"), "visit closed with reason corrected")
    h.check((await h.state("binary_sensor.guestbook_visit_active"))["state"] == "off", "visit_active off after correction")
    t2 = now()
    await h.answer(question, "RESIDENT", t2)  # the same token a second time
    await asyncio.sleep(2)
    h.check(not h.evs("guestbook_visit_corrected", t2), "a used token is ignored")
    await h.toggle("demo_front_door", False)
    h.entry["s1"] = entry_id


async def s2_ring_fingerprint(h: Harness):
    """Ring + fingerprint -> resident arrival, nothing in the calendars, no pushes."""
    t0 = now()
    await h.toggle("demo_fingerprint", True)
    await asyncio.sleep(2)
    await h.tap("demo_doorbell")
    await asyncio.sleep(2)
    await h.toggle("demo_front_door", True)
    await asyncio.sleep(8)
    h.check(not h.evs("guestbook_visit_started", t0), "no visit_started event")
    h.check(not await h.calendar(VISITS, t0), "visits calendar empty")
    h.check(not await h.calendar(RINGS, t0), "rings calendar empty")
    h.check((await h.state("binary_sensor.guestbook_visit_active"))["state"] == "off", "visit_active off")
    h.check(not h.push_list(IOS, t0) and not h.push_list(ANDROID, t0), "no pushes", (len(h.push_list(IOS, t0)),))
    await h.toggle("demo_front_door", False)
    await h.toggle("demo_fingerprint", False)
    h.entry["s2_time"] = t0


async def s3_unanswered_ring(h: Harness):
    """Ring alone -> unanswered ring in the rings calendar after the ring window, plus a push."""
    t0 = now()
    await h.tap("demo_doorbell")
    await asyncio.sleep(10)
    h.check(not await h.calendar(RINGS, t0), "pending ring is not shown yet")
    rings = await h.until(lambda: h.calendar(RINGS, t0), WINDOW + 20)
    h.check(rings and len(rings) == 1, "rings calendar has the ring after the window", rings)
    if rings:
        h.check(rings[0]["summary"] in ("Unanswered ring", "Klingel ohne Antwort"), "title is unanswered ring", rings[0]["summary"])
        h.entry["s3"] = rings[0].get("uid")
    h.check(not await h.calendar(VISITS, t0), "visits calendar empty")
    h.check(not h.evs("guestbook_visit_started", t0), "no visit events")
    await h.until(lambda: h.push_list(IOS, t0), 10)
    pushes = h.push_list(IOS, t0)
    h.check(len(pushes) == 1 and pushes[0].get("title") == "Unanswered ring", "unanswered ring push (switch is on)", [p.get("title") for p in pushes])


async def s4_guest_phone(h: Harness):
    """Alex home -> certain visit; arrival/end pushes only when the resident is away; away -> ends after grace."""
    # 4a: resident away
    t0 = now()
    await h.set_tracker(GUEST, "home")
    started = await h.until(lambda: h.evs("guestbook_visit_started", t0), 10)
    h.check(started and started[0]["certainty"] == "certain" and started[0]["guests"] == ["Alex"], "certain visit for Alex", started)
    h.check((await h.state("binary_sensor.alex_visiting"))["state"] == "on", "alex_visiting on")
    cur = await h.state("sensor.guestbook_current_visit")
    h.check(cur["state"] == "Alex", "current visit sensor says Alex", cur["state"])
    visits = await h.calendar(VISITS, t0)
    h.check(len(visits) == 1 and visits[0]["summary"] == "Visit: Alex", "visits calendar: Visit: Alex", visits and visits[0]["summary"])
    await h.until(lambda: h.push_list(IOS, t0), 10)
    pushes = h.push_list(IOS, t0)
    h.check(len(pushes) == 1 and "Alex" in pushes[0].get("message", ""), "arrival push while resident away (no question)", [p.get("message") for p in pushes])
    away = now()
    await h.set_tracker(GUEST, "not_home")
    await asyncio.sleep(20)
    h.check(not h.evs("guestbook_visit_ended", t0), "visit still open inside the phone grace")
    ended = await h.until(lambda: h.evs("guestbook_visit_ended", t0), WINDOW + 20)
    h.check(ended and ended[0]["reason"] == "guests_left", "ended with guests_left", ended)
    if ended:
        end = datetime.fromisoformat(ended[0]["end"])
        h.check(abs((end - away).total_seconds()) < 5, "end time is the moment the phone left", (end - away).total_seconds())
    h.check((await h.state("binary_sensor.alex_visiting"))["state"] == "off", "alex_visiting off")
    await h.until(lambda: len(h.push_list(IOS, t0)) >= 2, 10)
    h.check(len(h.push_list(IOS, t0)) == 2, "end push while resident away", len(h.push_list(IOS, t0)))

    # 4b: resident home -> no arrival push, no end push
    await h.set_tracker(RESIDENT, "home")
    h.check(await h.until(lambda: h._is("person.demo_resident", "home"), 10), "person is home (via the person's tracker)")
    t1 = now()
    await h.set_tracker(GUEST, "home")
    started = await h.until(lambda: h.evs("guestbook_visit_started", t1), 10)
    h.check(started, "visit starts with resident home")
    await asyncio.sleep(6)
    h.check(not h.push_list(IOS, t1), "no arrival push while the resident is home", len(h.push_list(IOS, t1)))
    await h.set_tracker(GUEST, "not_home")
    ended = await h.until(lambda: h.evs("guestbook_visit_ended", t1), WINDOW + 25)
    h.check(ended, "visit ends again")
    await asyncio.sleep(5)
    h.check(not h.push_list(IOS, t1), "no end push while the resident is home", len(h.push_list(IOS, t1)))
    await h.set_tracker(RESIDENT, "not_home")


async def s5_unavailable(h: Harness):
    """home -> unavailable -> not_home also ends the visit."""
    t0 = now()
    await h.set_tracker(GUEST, "home")
    h.check(await h.until(lambda: h.evs("guestbook_visit_started", t0), 10), "visit started")
    await asyncio.sleep(2)
    await h.rest("POST", f"/api/states/{GUEST}", {"state": "unavailable", "attributes": {}})
    await asyncio.sleep(5)
    h.check((await h.state("binary_sensor.alex_visiting"))["state"] == "on", "unavailable does not end the visit")
    away = now()
    await h.set_tracker(GUEST, "not_home")
    ended = await h.until(lambda: h.evs("guestbook_visit_ended", t0), WINDOW + 25)
    h.check(ended and ended[0]["reason"] == "guests_left", "not_home after unavailable ends the visit", ended)
    if ended:
        end = datetime.fromisoformat(ended[0]["end"])
        h.check(abs((end - away).total_seconds()) < 5, "end time is the not_home moment", (end - away).total_seconds())
    # and unavailable -> home -> unavailable -> not_home as well
    await h.set_tracker(GUEST, "home")
    t1 = now()
    h.check(await h.until(lambda: h.evs("guestbook_visit_started", t1), 10), "second visit started")
    await h.rest("POST", f"/api/states/{GUEST}", {"state": "unavailable", "attributes": {}})
    await asyncio.sleep(2)
    await h.set_tracker(GUEST, "not_home")
    h.check(await h.until(lambda: h.evs("guestbook_visit_ended", t1), WINDOW + 25), "second visit ends too")


async def s6_restart(h: Harness):
    """Restart HA during an open visit: the visit survives and the state is rebuilt."""
    t0 = now()
    await h.set_tracker(GUEST, "home")
    started = await h.until(lambda: h.evs("guestbook_visit_started", t0), 10)
    h.check(started, "visit started")
    entry_id = started[0]["entry_id"] if started else None
    # Entries are saved with a 5 s delay (SAVE_DELAY). `docker restart` is not a graceful stop of Home Assistant
    # (the recorder reports an unclean shutdown), so a change made less than 5 s before it is lost, like after
    # a power cut. Wait for the delayed save, as any real restart gives it the time.
    await asyncio.sleep(7)
    subprocess.run(["docker", "restart", "gb-dev-ha"], check=True, capture_output=True)
    await h.reconnect_after_restart()
    cur = await h.state("sensor.guestbook_current_visit")
    h.check(cur["state"] == "Alex" and cur["attributes"].get("entry_id") == entry_id, "same open visit after restart", cur)
    h.check((await h.state("binary_sensor.guestbook_visit_active"))["state"] == "on", "visit_active on after restart")
    visits = await h.calendar(VISITS, t0)
    h.check(len(visits) == 1 and visits[0]["uid"] == entry_id, "one calendar event, same entry", [v.get("uid") for v in visits])
    # test states are not persisted by HA: set them again, the open visit must not be duplicated
    await h.set_tracker(GUEST, "home")
    await asyncio.sleep(4)
    visits = await h.calendar(VISITS, t0)
    h.check(len(visits) == 1, "no duplicate visit when the phone state reappears", len(visits))
    h.check(len(h.evs("guestbook_visit_started", t0)) == 1, "no second started event", len(h.evs("guestbook_visit_started", t0)))
    away = now()
    await h.set_tracker(GUEST, "not_home")
    ended = await h.until(lambda: h.evs("guestbook_visit_ended", away), WINDOW + 25)
    h.check(ended and ended[0]["entry_id"] == entry_id, "the restored visit ends normally", ended)
    h.entry["s6"] = entry_id


async def s7_export(h: Harness):
    """guestbook.export returns a path and the file exists with the entries of the earlier scenarios."""
    res = await h.rest("POST", "/api/services/guestbook/export?return_response", {})
    out = res["service_response"]
    h.check("path" in out and out.get("count", 0) >= 1, "export returns path and count", out)
    name = Path(out["path"]).name
    file = ROOT / "dev" / "config" / "guestbook" / name
    h.check(file.exists(), "export file exists in dev/config/guestbook/", file)
    if not file.exists():
        return
    rows = [json.loads(line) for line in file.read_text().splitlines() if line.strip()]
    h.check(len(rows) == out["count"], "line count matches", (len(rows), out["count"]))
    kinds = {r["id"]: r for r in rows}
    s1 = kinds.get(h.entry.get("s1"))
    h.check(s1 and s1["kind"] == "visit" and (s1.get("correction") or {}).get("kind") == "delivery" and s1["reason"]["code"] == "ring_then_door", "S1 entry: visit + delivery correction kept next to the decision", s1 and (s1["reason"], s1.get("correction")))
    h.check(any(r["kind"] == "resident_arrival" and r["reason"]["code"] == "resident_signal" for r in rows), "resident arrival is stored in the export")
    h.check(kinds.get(h.entry.get("s3"), {}).get("kind") == "unanswered_ring", "unanswered ring is stored")
    h.check(any(r["reason"] and r["reason"]["code"] == "guest_phone" for r in rows), "guest_phone visits are stored")
    h.check(all(r["settings"].get("ring_window") == 60.0 for r in rows if r.get("settings")), "settings snapshot has 60 s windows")


async def s8_presence_visit_name(h: Harness):
    """Ring + presence -> visit; answer Visit with a name; lock log; door_then_quiet end (bonus)."""
    t0 = now()
    await h.tap("demo_doorbell")
    await asyncio.sleep(2)
    await h.toggle("demo_hallway", True)
    started = await h.until(lambda: h.evs("guestbook_visit_started", t0), 10)
    h.check(started and started[0]["certainty"] == "uncertain", "uncertain visit from presence", started)
    entry_id = started[0]["entry_id"] if started else None
    start_time = now()
    await h.until(lambda: any(p.get("data", {}).get("actions") for p in h.push_list(IOS, t0)), 10)
    question = next((p for p in h.push_list(IOS, t0) if p.get("data", {}).get("actions")), None)
    h.check(question, "question push captured")
    t1 = now()
    await h.answer(question, "VISIT", t1, reply_text="Sam")
    corrected = await h.until(lambda: h.evs("guestbook_visit_corrected", t1), 10)
    h.check(corrected and corrected[0]["kind"] == "visit" and corrected[0]["guest_name"] == "Sam", "corrected event with guest Sam", corrected)
    visits = await h.calendar(VISITS, t0)
    h.check(visits and visits[0]["summary"] == "Visit: Sam", "calendar title Visit: Sam", visits and visits[0]["summary"])
    issues = await h.client.call({"type": "repairs/list_issues"})
    h.check(any(i["domain"] == "guestbook" and i["issue_id"].startswith("guest_suggestion_") for i in issues["issues"]), "repair suggests creating guest Sam")
    # lock signal
    await h.client.call({"type": "call_service", "domain": "lock", "service": "unlock", "target": {"entity_id": "lock.demo_front_lock"}})
    await asyncio.sleep(2)
    await h.client.call({"type": "call_service", "domain": "lock", "service": "lock", "target": {"entity_id": "lock.demo_front_lock"}})
    await asyncio.sleep(2)
    visits = await h.calendar(VISITS, t0)
    h.check("lock" in (visits[0].get("description") or "").lower(), "lock changes are in the description", visits[0].get("description"))
    # end: door opening after the entry grace, then a quiet minute
    wait = WINDOW + 3 - (now() - start_time).total_seconds()
    await asyncio.sleep(max(wait, 0))
    await h.toggle("demo_hallway", False)
    leave = now()
    await h.toggle("demo_front_door", True)
    await asyncio.sleep(2)
    await h.toggle("demo_front_door", False)
    h.check(not h.evs("guestbook_visit_ended", t0), "visit still open right after the door opening")
    ended = await h.until(lambda: h.evs("guestbook_visit_ended", t0), WINDOW + 25)
    h.check(ended and ended[0]["reason"] == "door_then_quiet", "ended with door_then_quiet", ended)
    if ended:
        end = datetime.fromisoformat(ended[0]["end"])
        h.check(abs((end - leave).total_seconds()) < 5, "end time is the door opening", (end - leave).total_seconds())
    h.entry["s8"] = entry_id


SCENARIOS = {
    1: ("Ring + door, answer Delivery", s1_ring_door_delivery),
    2: ("Ring + fingerprint = resident", s2_ring_fingerprint),
    3: ("Ring alone = unanswered ring", s3_unanswered_ring),
    4: ("Alex phone home / away, pushes", s4_guest_phone),
    5: ("home > unavailable > not_home", s5_unavailable),
    6: ("Restart during open visit", s6_restart),
    7: ("guestbook.export", s7_export),
    8: ("Ring + presence, answer Visit 'Sam', door end", s8_presence_visit_name),
}
ORDER = [1, 2, 4, 5, 3, 6, 8, 7]  # the slow resident-window waits are cheaper in this order


async def reconnect_after_restart(h: Harness):
    await asyncio.sleep(5)
    end = time.monotonic() + 240
    while time.monotonic() < end:
        try:
            async with h.http.get(ws.URL + "/api/states/sensor.guestbook_current_visit", headers=HEADERS) as res:
                if res.status == 200:
                    break
        except aiohttp.ClientError:
            pass
        await asyncio.sleep(3)
    else:
        raise RuntimeError("HA did not come back")
    h.client.close()
    await h.connect()
    await asyncio.sleep(3)


Harness.reconnect_after_restart = reconnect_after_restart


async def main(selected):
    h = Harness()
    h.entry = {}
    await h.connect()
    results = {}
    for number in [n for n in ORDER if n in selected]:
        title, fn = SCENARIOS[number]
        print(f"\n== Scenario {number}: {title}", flush=True)
        start = len(h.checks)
        try:
            await h.reset()
            await fn(h)
        except Exception as err:  # noqa: BLE001
            h.check(False, f"scenario crashed: {type(err).__name__}", err)
            traceback.print_exc()
        mine = h.checks[start:]
        results[number] = {"title": title, "pass": bool(mine) and all(c[0] for c in mine),
                           "failed": [(c[1], c[2]) for c in mine if not c[0]], "checks": len(mine)}
    await h.reset()
    print("\n#  Scenario                                         Result  Checks")
    for number in sorted(results):
        r = results[number]
        print(f"{number:<2} {r['title']:<48} {'PASS' if r['pass'] else 'FAIL':<7} {r['checks'] - len(r['failed'])}/{r['checks']}")
        for name, detail in r["failed"]:
            print(f"     - {name}: {detail}")
    (ROOT / ".tmp").mkdir(exist_ok=True)
    (ROOT / ".tmp" / "scenario-results.json").write_text(json.dumps(results, indent=1, default=str))
    await h.http.close()


if __name__ == "__main__":
    asyncio.run(main({int(a) for a in sys.argv[1:]} or set(SCENARIOS)))
