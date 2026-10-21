"""Onboard the local test Home Assistant (http://localhost:8125) and store a token in dev/.env.

Creates a test user with a random password, finishes onboarding and creates a long-lived token.
Nothing is printed except status lines; credentials go to dev/.env (gitignored).
Run with the repo's venv:  .venv/bin/python dev/onboard.py
"""
import asyncio
import json
import secrets
from pathlib import Path

import aiohttp

BASE = "http://localhost:8125"
CLIENT_ID = f"{BASE}/"
ENV = Path(__file__).with_name(".env")


async def main() -> None:
    async with aiohttp.ClientSession() as s:
        for _ in range(60):
            try:
                async with s.get(f"{BASE}/api/onboarding") as r:
                    if r.status == 200:
                        steps = await r.json()
                        break
            except aiohttp.ClientError:
                pass
            await asyncio.sleep(5)
        else:
            raise SystemExit("Home Assistant did not come up")
        done = {st["step"] for st in steps if st["done"]}
        if "user" in done:
            raise SystemExit("Already onboarded; token must already be in dev/.env")
        user, pw = "dev", secrets.token_urlsafe(18)
        async with s.post(f"{BASE}/api/onboarding/users", json={
            "client_id": CLIENT_ID, "name": "Dev", "username": user, "password": pw, "language": "en"}) as r:
            r.raise_for_status()
            code = (await r.json())["auth_code"]
        async with s.post(f"{BASE}/auth/token", data={
            "grant_type": "authorization_code", "code": code, "client_id": CLIENT_ID}) as r:
            r.raise_for_status()
            access = (await r.json())["access_token"]
        hdr = {"Authorization": f"Bearer {access}"}
        for step, body in [("core_config", {}), ("analytics", {}),
                           ("integration", {"client_id": CLIENT_ID, "redirect_uri": f"{BASE}/?auth_callback=1"})]:
            async with s.post(f"{BASE}/api/onboarding/{step}", json=body, headers=hdr) as r:
                print(step, r.status)
        async with s.ws_connect(f"{BASE}/api/websocket") as ws:
            await ws.receive_json()
            await ws.send_json({"type": "auth", "access_token": access})
            await ws.receive_json()
            await ws.send_json({"id": 1, "type": "auth/long_lived_access_token", "client_name": "guestbook-dev", "lifespan": 3650})
            token = (await ws.receive_json())["result"]
        ENV.write_text(f"HA_URL={BASE}\nHA_USER={user}\nHA_PASSWORD={pw}\nHA_TOKEN={token}\n")
        ENV.chmod(0o600)
        print("onboarded, token stored in dev/.env")


asyncio.run(main())
