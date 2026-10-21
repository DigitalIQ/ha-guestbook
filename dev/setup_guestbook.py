"""Set up Guestbook in the dev HA: person, fake Companion phones, guest tracker, config flow, guest, options.

Usage: .venv/bin/python dev/setup_guestbook.py
Reads dev/.env. Safe to run again: existing pieces are skipped. The webhook ids of the fake phones are
stored in dev/.env (GB_IOS_WEBHOOK, GB_ANDROID_WEBHOOK); nothing secret is printed.
"""

import asyncio
import sys

import aiohttp

import ws

PHONES = {
    "GB_IOS_WEBHOOK": dict(device_name="Demo Phone", os_name="iOS", manufacturer="Apple", model="iPhone", device_id="gb-demo-ios"),
    "GB_ANDROID_WEBHOOK": dict(device_name="Demo Android", os_name="Android", manufacturer="Google", model="Pixel", device_id="gb-demo-android"),
}
RESIDENT_TRACKER = "device_tracker.demo_resident_phone"
GUEST_TRACKER = "device_tracker.demo_alex_phone"
HEADERS = {"Authorization": f"Bearer {ws.ENV['HA_TOKEN']}"}


async def rest(session, method, path, body=None):
    async with session.request(method, ws.URL + path, json=body, headers=HEADERS) as res:
        if res.status >= 400:
            raise RuntimeError(f"{method} {path}: {res.status} {(await res.text())[:300]}")
        return await res.json() if res.content_type == "application/json" else None


async def set_state(session, entity_id, state):
    await rest(session, "POST", f"/api/states/{entity_id}", {"state": state, "attributes": {"source_type": "router"}})


async def flow_step(session, base, flow, data):
    res = await rest(session, "POST", f"{base}/{flow['flow_id']}", data)
    return res


async def main():
    async with aiohttp.ClientSession() as session:
        client = await ws.connect(session)

        # Person with a fake tracker
        await set_state(session, RESIDENT_TRACKER, "not_home")
        persons = await client.call({"type": "person/list"})
        if not any(p["name"] == "Demo Resident" for p in persons["storage"]):
            await client.call({"type": "person/create", "name": "Demo Resident", "device_trackers": [RESIDENT_TRACKER]})
            print("person created")
        await set_state(session, GUEST_TRACKER, "not_home")

        # Fake Companion phones (local push over the websocket channel)
        env_text = ws.ENV_FILE.read_text()
        for key, phone in PHONES.items():
            if key in ws.ENV:
                continue
            reg = await rest(session, "POST", "/api/mobile_app/registrations", {
                "app_id": "io.robbie.HomeAssistant", "app_name": "Home Assistant", "app_version": "2026.10.0",
                "os_version": "19.0", "supports_encryption": False, "app_data": {"push_websocket_channel": True}, **phone,
            })
            env_text += f"{key}={reg['webhook_id']}\n"
            ws.ENV[key] = reg["webhook_id"]
            print("registered", phone["device_name"])
        ws.ENV_FILE.write_text(env_text)
        ws.ENV_FILE.chmod(0o600)

        # Config flow
        entries = [e for e in await rest(session, "GET", "/api/config/config_entries/entry") if e["domain"] == "guestbook"]
        if not entries:
            flow = await rest(session, "POST", "/api/config/config_entries/flow", {"handler": "guestbook"})
            res = await flow_step(session, "/api/config/config_entries/flow", flow, {
                "doorbells": ["binary_sensor.demo_doorbell"],
                "doors": ["binary_sensor.demo_front_door"],
                "presence": ["binary_sensor.demo_hallway_presence"],
                "locks": ["lock.demo_front_lock"],
                "residents": ["person.demo_resident"],
                "resident_signals": ["binary_sensor.demo_fingerprint"],
            })
            print("config flow:", res["type"])
            entries = [e for e in await rest(session, "GET", "/api/config/config_entries/entry") if e["domain"] == "guestbook"]
        entry_id = entries[0]["entry_id"]

        # Guest Alex
        if not entries[0].get("num_subentries"):
            flow = await rest(session, "POST", "/api/config/config_entries/subentries/flow", {"handler": [entry_id, "guest"]})
            res = await flow_step(session, "/api/config/config_entries/subentries/flow", flow, {"name": "Alex", "trackers": [GUEST_TRACKER]})
            print("guest flow:", res["type"])

        # Options: smallest rule values, pushes to both phones, all switches on
        devices = await client.call({"type": "config/device_registry/list"})
        phones = [d["id"] for d in devices if d["name"] in ("Demo Phone", "Demo Android")]
        if len(phones) != 2:
            sys.exit(f"expected 2 phone devices, found {len(phones)}")
        for step, data in {
            "rules": {"ring_window": 1, "resident_window": 1, "quiet_period": 1, "entry_grace": 1,
                      "phone_grace": 1, "max_duration": 0.5, "retention": 1},
            "pushes": {"phones": phones, "notify_entities": [], "push_arrival": True, "push_end": True,
                       "push_correction": True, "push_unanswered_ring": True},
        }.items():
            flow = await rest(session, "POST", "/api/config/config_entries/options/flow", {"handler": entry_id})
            flow = await flow_step(session, "/api/config/config_entries/options/flow", flow, {"next_step_id": step})
            res = await flow_step(session, "/api/config/config_entries/options/flow", flow, data)
            print("options", step, res["type"])
        client.close()


asyncio.run(main())
