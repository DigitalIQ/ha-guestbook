"""Send WebSocket commands to the dev HA and print the results as JSON.

Usage: .venv/bin/python dev/ws.py '{"type": "config/entity_registry/list"}' ['{"type": ...}' ...]
Reads HA_URL and HA_TOKEN from dev/.env. Also importable: `connect(session)` returns a Client with
`call(msg)` (result of a command) and `subscribe(msg, handler)` (events of a subscription).
"""

import asyncio
import json
import sys
from pathlib import Path

import aiohttp

ENV_FILE = Path(__file__).parent / ".env"
ENV = dict(line.split("=", 1) for line in ENV_FILE.read_text().splitlines() if "=" in line)
URL = ENV["HA_URL"].rstrip("/")
WS_URL = URL.replace("http", "ws", 1) + "/api/websocket"


class Client:
    def __init__(self, ws):
        self.ws = ws
        self.next_id = 1
        self._results: dict[int, asyncio.Future] = {}
        self._handlers: dict[int, object] = {}
        self._reader = asyncio.ensure_future(self._read())

    async def _read(self):
        async for msg in self.ws:
            if msg.type != aiohttp.WSMsgType.TEXT:
                continue
            data = json.loads(msg.data)
            if data.get("type") == "result" and data["id"] in self._results:
                self._results.pop(data["id"]).set_result(data)
            elif data.get("type") == "event" and data["id"] in self._handlers:
                self._handlers[data["id"]](data["event"])

    async def call(self, msg: dict, handler=None):
        """Send a command and return its result. `handler` receives the events of a subscription."""
        msg_id = self.next_id
        self.next_id += 1
        if handler is not None:
            self._handlers[msg_id] = handler
        future = self._results[msg_id] = asyncio.get_running_loop().create_future()
        await self.ws.send_json({**msg, "id": msg_id})
        res = await asyncio.wait_for(future, 60)
        if not res.get("success"):
            raise RuntimeError(json.dumps(res.get("error")))
        return res.get("result")

    async def subscribe(self, msg: dict, handler):
        return await self.call(msg, handler)

    def close(self):
        self._reader.cancel()


async def connect(session) -> Client:
    ws = await session.ws_connect(WS_URL)
    await ws.receive_json()
    await ws.send_json({"type": "auth", "access_token": ENV["HA_TOKEN"]})
    if (await ws.receive_json()).get("type") != "auth_ok":
        raise RuntimeError("auth failed")
    return Client(ws)


async def main(messages):
    async with aiohttp.ClientSession() as session:
        client = await connect(session)
        for m in messages:
            print(json.dumps(await client.call(json.loads(m)), ensure_ascii=False))
        client.close()


if __name__ == "__main__":
    asyncio.run(main(sys.argv[1:]))
