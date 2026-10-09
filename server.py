#!/usr/bin/env python3
import argparse
import asyncio
import contextlib
from dataclasses import dataclass
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import time

from aiohttp import web, WSMsgType

from game.simulation import Room, new_player
from game.world import BLOCKS, DAY_LENGTH, DAY_FRACTION, HEIGHT, ITEMS, RECIPES, SIZE, RuleError

ROOT = Path(__file__).resolve().parent
LOG = logging.getLogger("wildwood")
ROOM_NAMES = ("FERN", "TIDE", "EMBER")
APP_STATE = web.AppKey("state", dict)
APP_ASSETS = web.AppKey("assets", dict)
DELIVERY = "buffered-v2"
PUBLIC_FILES = {
    "index.html": "text/html",
    "style.css": "text/css",
    "client.js": "text/javascript",
    "controls.js": "text/javascript",
    "renderer.js": "text/javascript",
    "vendor/three.module.js": "text/javascript",
    "vendor/three.core.js": "text/javascript",
    "vendor/THREE-LICENSE.txt": "text/plain",
}


@dataclass(frozen=True)
class Asset:
    body: bytes
    content_type: str
    etag: str


def load_assets(public):
    assets = {}
    if public.is_symlink():
        raise RuntimeError("The public asset directory must not be a symlink.")
    for name, content_type in PUBLIC_FILES.items():
        path = public
        for part in Path(name).parts:
            path /= part
            if path.is_symlink():
                raise RuntimeError(f"Public assets must not contain symlinks: {name}")
        body = path.read_bytes()
        assets[name] = Asset(body, content_type, hashlib.sha256(body).hexdigest())
    return assets


def save_room(room, directory):
    directory.mkdir(parents=True, exist_ok=True)
    obj = {"version": 1, "seed": room.world.seed, "edits": room.world.edits,
           "chests": room.world.chests, "clock": room.world.clock, "won": room.world.won,
           "players": {pid: {k: p[k] for k in ("name", "inv", "pos", "yaw", "pitch",
                       "hp", "hunger", "oxygen", "deaths")} for pid, p in room.players.items()},
           "mobs": room.mobs}
    path = directory / f"{room.name}.json"
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(obj), encoding="utf-8")
    os.replace(temp, path)


def load_room(name, directory):
    path = directory / f"{name}.json"
    if not path.exists():
        return Room(name)
    obj = json.loads(path.read_text(encoding="utf-8"))
    if obj["version"] != 1:
        raise ValueError(f"Unsupported save version in {path}")
    room = Room(name, obj["seed"])
    for i, b in obj["edits"].items():
        room.world.blocks[int(i)] = b
    room.world.edits = obj["edits"]
    room.world.chests = obj["chests"]
    room.world.clock = obj["clock"]
    room.world.won = obj["won"]
    room.mobs = obj["mobs"]
    for pid, saved in obj["players"].items():
        p = new_player(pid, room.world, len(room.players) + 1)
        p.update(saved)
        if room.world.collides(p["pos"]):
            p["pos"] = room.world.spawn()
        room.players[pid] = p
    return room


def number(value, low, high):
    if type(value) not in (int, float) or not math.isfinite(value):
        raise RuleError("Invalid movement input.")
    return max(low, min(high, value))


async def websocket(request):
    state = request.app[APP_STATE]
    ws = web.WebSocketResponse(heartbeat=15, max_msg_size=4096)
    await ws.prepare(request)
    room = None
    pid = None
    window, packets = time.monotonic(), 0
    try:
        async for event in ws:
            if event.type != WSMsgType.TEXT:
                if event.type == WSMsgType.ERROR:
                    LOG.warning("WebSocket error: %s", ws.exception())
                continue
            now = time.monotonic()
            if now - window >= 1:
                window, packets = now, 0
            packets += 1
            if packets > 75:
                await ws.close(code=1008, message=b"Too many messages")
                break
            try:
                msg = json.loads(event.data)
                if not isinstance(msg, dict):
                    raise RuleError("Expected a message object.")
                kind = msg.get("type")
                if kind == "join":
                    if room is not None:
                        raise RuleError("Already connected to a room.")
                    name = msg.get("room")
                    token = msg.get("token")
                    if name not in ROOM_NAMES or not isinstance(token, str) or not re.fullmatch(r"[a-f0-9]{32}", token):
                        raise RuleError("Choose FERN, TIDE, or EMBER and reconnect.")
                    candidate = state["rooms"].get(name)
                    if candidate is None:
                        candidate = load_room(name, state["directory"])
                        state["rooms"][name] = candidate
                    key = (name, token)
                    old_connection = state["connections"].get(key)
                    if old_connection is not None and msg.get("reconnect") is not True:
                        raise RuleError("This scout is already playing in another tab. Use a different browser profile.")
                    if old_connection is None and sum(p["online"] for p in candidate.players.values()) >= 8:
                        raise RuleError("Room full (8 scouts). Choose another room.")
                    if token not in candidate.players and len(candidate.players) >= 128:
                        raise RuleError("This room has reached its saved-scout limit. Choose another room.")
                    room, pid = candidate, token
                    if pid not in room.players:
                        room.players[pid] = new_player(pid, room.world, len(room.players) + 1)
                    p = room.players[pid]
                    state["connections"][key] = ws
                    if old_connection is not None:
                        await old_connection.close(code=1001, message=b"Scout reconnected")
                    p.update(online=True, input_at=room.time, input={"x": 0, "z": 0, "jump": False})
                    await ws.send_json({"type": "welcome", "id": pid, "room": name,
                                        "size": SIZE, "height": HEIGHT, "blocks": room.world.encoded(),
                                        "catalog": BLOCKS, "items": ITEMS, "recipes": RECIPES,
                                        "dayLength": DAY_LENGTH, "dayFraction": DAY_FRACTION,
                                        "state": room.snapshot(pid)})
                elif room is None:
                    raise RuleError("Join a room first.")
                elif kind == "input":
                    p = room.players[pid]
                    p["input"] = {"x": number(msg.get("x", 0), -1, 1),
                                  "z": number(msg.get("z", 0), -1, 1),
                                  "jump": msg.get("jump") is True}
                    p["yaw"] = number(msg.get("yaw", 0), -100000, 100000) % (2 * math.pi)
                    p["pitch"] = number(msg.get("pitch", 0), -1.5, 1.5)
                    p["input_at"] = room.time
                elif kind == "action":
                    text = room.action(pid, msg)
                    await ws.send_json({"type": "notice", "text": text})
                else:
                    raise RuleError("Unknown message.")
            except (RuleError, json.JSONDecodeError) as exc:
                await ws.send_json({"type": "error", "text": str(exc)})
    finally:
        if room is not None and pid is not None and state["connections"].get((room.name, pid)) is ws:
            room.players[pid]["online"] = False
            room.players[pid]["input"] = {"x": 0, "z": 0, "jump": False}
            state["connections"].pop((room.name, pid), None)
            try:
                save_room(room, state["directory"])
            except OSError:
                LOG.exception("Could not save room after disconnect")
    return ws


async def simulation(app):
    state = app[APP_STATE]
    last = time.monotonic()
    broadcast = 0
    save_at = last + 10
    while True:
        await asyncio.sleep(0.05)
        now = time.monotonic()
        dt = min(now - last, 0.15)
        last = now
        for room in state["rooms"].values():
            room.tick(dt)
        broadcast += 1
        if broadcast % 2 == 0:
            # Swap buffers before awaiting I/O: actions arriving during a broadcast
            # must survive for the next batch and reach every scout.
            batches = {name: (room.changes, room.events) for name, room in state["rooms"].items()}
            for room in state["rooms"].values():
                room.changes, room.events = [], []
            for (name, pid), ws in list(state["connections"].items()):
                if not ws.closed:
                    try:
                        snapshot = state["rooms"][name].snapshot(pid)
                        snapshot["changes"], snapshot["events"] = batches[name]
                        await asyncio.wait_for(ws.send_json(snapshot), timeout=0.5)
                    except (ConnectionError, asyncio.TimeoutError):
                        LOG.warning("Closing unresponsive scout in %s", name)
                        await ws.close()
        if now >= save_at:
            save_at = now + 10
            try:
                for room in state["rooms"].values():
                    save_room(room, state["directory"])
                state["save_error"] = None
            except OSError as exc:
                LOG.exception("World save failed")
                state["save_error"] = str(exc)
                for ws in list(state["connections"].values()):
                    if not ws.closed:
                        await ws.send_json({"type": "error", "text": "Server could not save. Ask the host to check disk space."})


async def lifecycle(app):
    task = asyncio.create_task(simulation(app))
    yield
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    state = app[APP_STATE]
    for ws in list(state["connections"].values()):
        await ws.close(code=1001, message=b"Server stopping")
    for room in state["rooms"].values():
        save_room(room, state["directory"])


async def index(request):
    asset = request.app[APP_ASSETS]["index.html"]
    # Use the same normal HTTP writer as /health, not macOS native sendfile.
    return web.Response(body=asset.body, content_type=asset.content_type, charset="utf-8",
                        headers={"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff",
                                 "X-Wildwood-Delivery": DELIVERY})


async def static_asset(request):
    name = request.match_info["path"]
    asset = request.app[APP_ASSETS].get(name)
    if asset is None or name == "index.html":
        raise web.HTTPNotFound(text="Game asset not found.")
    headers = {"Cache-Control": "public, max-age=0, must-revalidate",
               "ETag": f'"{asset.etag}"', "X-Content-Type-Options": "nosniff",
               "X-Wildwood-Delivery": DELIVERY}
    if request.if_none_match and any(tag.value in (asset.etag, "*") for tag in request.if_none_match):
        return web.Response(status=304, headers=headers)
    # Fixed allowlist and cached bytes avoid request-derived disk paths and
    # repeated reads of the vendor library. Range requests receive the full file.
    return web.Response(body=asset.body, content_type=asset.content_type, charset="utf-8",
                        headers=headers)


async def health(request):
    state = request.app[APP_STATE]
    return web.json_response({"ok": state["save_error"] is None, "game": "Wildwood Keep",
                             "rooms": ROOM_NAMES, "scouts": len(state["connections"]),
                             "saveError": state["save_error"], "delivery": DELIVERY},
                            headers={"Cache-Control": "no-store", "X-Wildwood-Delivery": DELIVERY})


def create_app(directory=None):
    app = web.Application(client_max_size=8192)
    app[APP_ASSETS] = load_assets(ROOT / "public")
    app[APP_STATE] = {"rooms": {}, "connections": {},
                      "directory": Path(directory) if directory else ROOT / "data",
                      "save_error": None}
    app.router.add_get("/", index)
    app.router.add_get("/play", index)
    app.router.add_get("/health", health)
    app.router.add_get("/ws", websocket)
    app.router.add_get("/assets/{path:.*}", static_asset)
    app.cleanup_ctx.append(lifecycle)
    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Wildwood Keep local multiplayer server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--data", default=str(ROOT / "data"))
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    web.run_app(create_app(args.data), host=args.host, port=args.port,
                access_log=LOG, access_log_format='%a "%r" %s %b')
