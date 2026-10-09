import asyncio
import copy
import math
from pathlib import Path
import tempfile
import unittest

from aiohttp import ClientSession
from aiohttp.test_utils import TestServer

from game.simulation import Room, new_player
from game.world import (DAY_FRACTION, DAY_LENGTH, ITEMS, RECIPES, SLOTS, RuleError,
                        World, add_items, count, craft, is_night)
from server import APP_STATE, PUBLIC_FILES, ROOT, create_app, load_assets, load_room, number, save_room


class InventoryTests(unittest.TestCase):
    def test_overflow_is_atomic(self):
        inv = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        before = copy.deepcopy(inv)
        with self.assertRaises(RuleError):
            add_items(inv, {"berry": 1})
        self.assertEqual(inv, before)

    def test_stacks_and_tools_respect_limits(self):
        inv = [None] * SLOTS
        add_items(inv, {"log": 70, "pick": 2})
        self.assertEqual([s["count"] for s in inv[:5]], [32, 32, 6, 1, 1])

    def test_crafting_missing_costs_is_atomic(self):
        inv = [None] * SLOTS
        add_items(inv, {"log": 2, "stone": 2})
        before = copy.deepcopy(inv)
        with self.assertRaises(RuleError):
            craft(inv, "pick")
        self.assertEqual(inv, before)

    def test_crafting_output_overflow_is_atomic(self):
        inv = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        inv[0] = {"item": "log", "count": 2}
        before = copy.deepcopy(inv)
        with self.assertRaises(RuleError):
            craft(inv, "planks")
        self.assertEqual(inv, before)

    def test_craft_uses_freed_slot(self):
        inv = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        inv[0] = {"item": "log", "count": 1}
        craft(inv, "planks")
        self.assertEqual(inv[0], {"item": "plank", "count": 4})

    def test_all_recipes_are_valid_and_atomic(self):
        for recipe, r in RECIPES.items():
            inv = [None] * SLOTS
            add_items(inv, r["cost"])
            craft(inv, recipe)
            for item, amount in r["out"].items():
                self.assertEqual(count(inv, item), amount)
                self.assertIn(item, ITEMS)

    def test_untrusted_recipe_shapes(self):
        for value in [None, [], {}, 12, "imaginary"]:
            with self.assertRaises(RuleError):
                craft([None] * SLOTS, value)


class StaticAssetTests(unittest.TestCase):
    def test_asset_symlinks_are_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            public = root / "public"
            public.mkdir()
            target = root / "private.txt"
            target.write_text("Not a public game asset.", encoding="utf-8")
            (public / "index.html").symlink_to(target)
            with self.assertRaisesRegex(RuntimeError, "symlinks"):
                load_assets(public)


class WorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = World()

    def setUp(self):
        self.world = copy.deepcopy(self.base)
        self.p = new_player("a", self.world, 1)
        self.p["online"] = True

    def test_spawn_is_safe_and_resources_and_water_exist(self):
        self.assertFalse(self.world.collides(self.world.spawn()))
        for b in [1, 3, 4, 5, 6, 8, 10]:
            self.assertGreater(self.world.blocks.count(b), 0)

    def test_rle_round_trip(self):
        runs = self.world.encoded()
        decoded = [b for i in range(0, len(runs), 2) for b in [runs[i]] * runs[i + 1]]
        self.assertEqual(decoded, self.world.blocks)

    def test_mining_collects_and_overflow_preserves_block(self):
        self.p["pos"] = [18.5, 8.05, 17.5]
        self.world.set(18, 9, 14, 4)
        hit = self.world.ray([18.5, 9.55, 17.5], [0, 0, -1])
        self.assertEqual(hit[0], (18, 9, 14))
        self.world.mine(self.p, hit)
        self.assertEqual(count(self.p["inv"], "log"), 7)
        self.assertEqual(self.world.get(18, 9, 14), 0)
        self.world.set(18, 9, 14, 4)
        self.p["inv"] = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        with self.assertRaises(RuleError):
            self.world.mine(self.p, hit)
        self.assertEqual(self.world.get(18, 9, 14), 4)

    def test_mining_stone_requires_pick(self):
        self.p["pos"] = [18.5, 8.05, 17.5]
        self.world.set(18, 9, 14, 8)
        hit = self.world.ray([18.5, 9.55, 17.5], [0, 0, -1])
        with self.assertRaises(RuleError):
            self.world.mine(self.p, hit)
        craft(self.p["inv"], "pick")
        self.world.mine(self.p, hit)
        self.assertEqual(count(self.p["inv"], "copper"), 1)

    def test_placement_consumes_and_protects_players(self):
        self.world.set(18, 9, 14, 3)
        self.world.set(18, 9, 15, 0)
        hit = ((18, 9, 14), (18, 9, 15), 3)
        slot = next(i for i, s in enumerate(self.p["inv"]) if s and s["item"] == "dirt")
        before = count(self.p["inv"], "dirt")
        other = {"pos": [18.5, 8.2, 15.5]}
        with self.assertRaises(RuleError):
            self.world.place(self.p, hit, slot, [other])
        self.assertEqual(count(self.p["inv"], "dirt"), before)
        self.world.place(self.p, hit, slot, [self.p])
        self.assertEqual(self.world.get(18, 9, 15), 2)
        self.assertEqual(count(self.p["inv"], "dirt"), before - 1)

    def test_chest_loot_is_once_and_overflow_does_not_empty(self):
        key = next(iter(self.world.chests))
        xyz = tuple(map(int, key.split(",")))
        hit = (xyz, xyz, 10)
        self.p["inv"] = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        with self.assertRaises(RuleError):
            self.world.open_chest(self.p, hit)
        self.assertFalse(self.world.chests[key]["opened"])
        self.p["inv"] = [None] * SLOTS
        self.world.open_chest(self.p, hit)
        self.assertTrue(self.world.chests[key]["opened"])
        with self.assertRaises(RuleError):
            self.world.open_chest(self.p, hit)

    def test_beacon_completes_world(self):
        self.p["inv"] = [None] * SLOTS
        add_items(self.p["inv"], {"relic": 3, "copper": 8, "plank": 12})
        craft(self.p["inv"], "beacon")
        self.world.set(18, 9, 15, 0)
        slot = next(i for i, s in enumerate(self.p["inv"]) if s)
        self.world.place(self.p, ((18, 9, 14), (18, 9, 15), 3), slot, [self.p])
        self.assertTrue(self.world.won)

    def test_day_night_boundaries(self):
        self.assertFalse(is_night(DAY_LENGTH * DAY_FRACTION - .01))
        self.assertTrue(is_night(DAY_LENGTH * DAY_FRACTION))
        self.assertFalse(is_night(DAY_LENGTH))

    def test_collision_and_swimming(self):
        room = Room("FERN")
        room.players["a"] = self.p
        self.p["pos"] = [44.5, 3.0, 32.5]
        self.p["input"] = {"x": 0, "z": 0, "jump": True}
        start = self.p["pos"][1]
        for _ in range(20):
            self.p["input_at"] = room.time
            room.tick(.05)
        self.assertGreater(self.p["pos"][1], start)
        self.assertLess(self.p["oxygen"], 100)
        self.assertTrue(room.world.collides([13.5, 7.0, 14.5]))

    def test_night_spawns_hostiles_dawn_removes(self):
        room = Room("FERN")
        room.players["a"] = self.p
        room.world.clock = DAY_LENGTH * DAY_FRACTION - .01
        room.tick(.05)
        self.assertTrue(any(m["kind"] in ("zombie", "skeleton") for m in room.mobs))
        room.world.clock = DAY_LENGTH - .01
        room.tick(.05)
        self.assertFalse(any(m["kind"] in ("zombie", "skeleton") for m in room.mobs))

    def test_bosses_dormant_distinct_and_combat_loot(self):
        room = Room("FERN")
        room.players["a"] = self.p
        bosses = [m for m in room.mobs if m["boss"]]
        self.assertEqual(len({m["attack"] for m in bosses}), 3)
        self.assertTrue(all(not m["awake"] for m in bosses))
        boss = bosses[0]
        # An unobstructed controlled arena exercises the actual aiming/attack path.
        for x in range(10, 18):
            for z in range(10, 18):
                for y in range(8, 15):
                    room.world.set(x, y, z, 0)
        boss["pos"] = [13.5, 8.05, 12.5]
        boss["hp"] = 7
        self.p["pos"] = [13.5, 8.05, 15.5]
        self.p["yaw"] = 0
        self.p["pitch"] = 0
        room.action("a", {"action": "mine"})
        self.assertEqual(boss["hp"], 0)
        self.assertEqual(count(self.p["inv"], "relic"), 1)

    def test_each_boss_telegraphs_and_executes_distinct_attack(self):
        for kind in ("thorn", "tide", "ember"):
            room = Room("FERN")
            boss = next(m for m in room.mobs if m["kind"] == kind)
            room.mobs = [boss]
            p = new_player("a", room.world, 1)
            p.update(online=True, pos=[13.5, 8.05, 15.5])
            room.players["a"] = p
            for x in range(10, 18):
                for z in range(10, 18):
                    for y in range(8, 15):
                        room.world.set(x, y, z, 0)
            boss.update(pos=[13.5, 8.05, 12.5], awake=True, special=0)
            room.tick(.05)
            self.assertGreater(boss["windup"], 1, kind)
            for _ in range(40):
                room.tick(.05)
                if boss["windup"] <= 0:
                    break
            self.assertEqual(boss["windup"] <= 0, True)
            if kind == "thorn":
                self.assertLess(p["hp"], 80)
            elif kind == "tide":
                self.assertTrue(room.projectiles)
                self.assertEqual(room.projectiles[0]["damage"], 18)
            else:
                self.assertGreater(boss["charge"], 0)

    def test_idle_room_pauses_clock(self):
        room = Room("FERN")
        before = room.world.clock
        room.tick(20)
        self.assertEqual(room.world.clock, before)

    def test_sharing_relics_is_atomic_and_allows_cooperative_goal(self):
        room = Room("FERN")
        room.players["a"] = self.p
        other = new_player("b", room.world, 2)
        other["online"] = True
        room.players["b"] = other
        add_items(self.p["inv"], {"relic": 2})
        slot = next(i for i, s in enumerate(self.p["inv"]) if s and s["item"] == "relic")
        other["inv"] = [{"item": "stone", "count": 32} for _ in range(SLOTS)]
        before = copy.deepcopy(self.p["inv"])
        with self.assertRaises(RuleError):
            room.action("a", {"action": "give", "slot": slot, "target": "b"})
        self.assertEqual(self.p["inv"], before)
        other["inv"] = [None] * SLOTS
        add_items(other["inv"], {"relic": 1, "copper": 8, "plank": 12})
        room.action("a", {"action": "give", "slot": slot, "target": "b"})
        self.assertEqual(count(other["inv"], "relic"), 3)
        self.assertEqual(count(self.p["inv"], "relic"), 0)
        craft(other["inv"], "beacon")
        self.assertEqual(count(other["inv"], "beacon"), 1)

    def test_save_reload_restores_world_inventory_bosses_chests(self):
        room = Room("FERN")
        room.players["a"] = self.p
        room.world.set(22, 10, 22, 9, edit=True)
        room.mobs[-1]["hp"] = 42
        room.world.clock = 300
        key = next(iter(room.world.chests))
        room.world.chests[key]["opened"] = True
        with tempfile.TemporaryDirectory() as directory:
            save_room(room, Path(directory))
            restored = load_room("FERN", Path(directory))
        self.assertEqual(restored.world.get(22, 10, 22), 9)
        self.assertEqual(restored.players["a"]["inv"], self.p["inv"])
        self.assertFalse(restored.players["a"]["online"])
        self.assertEqual(restored.world.clock, 300)
        self.assertEqual(restored.mobs[-1]["hp"], 42)
        self.assertTrue(restored.world.chests[key]["opened"])

    def test_finite_input_validation(self):
        for value in [float("nan"), float("inf"), "1", True, [], None]:
            with self.assertRaises(RuleError):
                number(value, -1, 1)
        self.assertEqual(number(100, -1, 1), 1)


class NetworkTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.app = create_app(self.tmp.name)
        self.server = TestServer(self.app)
        await self.server.start_server()
        self.client = ClientSession()
        self.sockets = []

    async def asyncTearDown(self):
        for ws in self.sockets:
            await ws.close()
        await self.client.close()
        await self.server.close()
        self.tmp.cleanup()

    async def join(self, token, room="FERN"):
        ws = await self.client.ws_connect(self.server.make_url("/ws"))
        self.sockets.append(ws)
        await ws.send_json({"type": "join", "room": room, "token": token})
        msg = await ws.receive_json(timeout=4)
        self.assertEqual(msg["type"], "welcome", msg)
        return ws, msg

    async def receive_type(self, ws, kind):
        for _ in range(40):
            msg = await ws.receive_json(timeout=3)
            if msg["type"] == kind:
                return msg
        self.fail(f"Did not receive {kind}")

    async def test_html_uses_complete_normal_response_for_browser_headers(self):
        cases = [
            {},
            {"Accept-Encoding": "gzip, deflate, br", "Accept": "text/html",
             "User-Agent": "Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X)"},
            {"Range": "bytes=0-255", "If-Range": '"old-file-etag"'},
            {"If-None-Match": "*", "If-Modified-Since": "Wed, 01 Jan 2030 00:00:00 GMT"},
        ]
        for path in ["/?v=tablet2", "/play?v=tablet2"]:
            for headers in cases:
                async with self.client.get(self.server.make_url(path), headers=headers) as response:
                    body = await response.read()
                    self.assertEqual(response.status, 200)
                    self.assertEqual(body, (ROOT / "public/index.html").read_bytes())
                    self.assertEqual(int(response.headers["Content-Length"]), len(body))
                    self.assertEqual(response.headers["Content-Type"], "text/html; charset=utf-8")
                    self.assertEqual(response.headers["Cache-Control"], "no-store")
                    self.assertEqual(response.headers["X-Wildwood-Delivery"], "buffered-v2")
                    self.assertNotIn("Content-Encoding", response.headers)
                    self.assertNotIn("Transfer-Encoding", response.headers)
                    self.assertNotIn("Content-Range", response.headers)

    async def test_head_has_correct_length_and_no_body(self):
        for path in ["/", "/play", "/assets/vendor/three.core.js"]:
            async with self.client.head(self.server.make_url(path)) as response:
                self.assertEqual(response.status, 200)
                self.assertEqual(await response.read(), b"")
                file = "index.html" if path in ("/", "/play") else path.removeprefix("/assets/")
                self.assertEqual(int(response.headers["Content-Length"]),
                                 (ROOT / "public" / file).stat().st_size)

    async def test_assets_mime_full_body_and_etag_revalidation(self):
        for file, content_type in PUBLIC_FILES.items():
            if file == "index.html":
                continue
            async with self.client.get(self.server.make_url(f"/assets/{file}"),
                                       headers={"Accept-Encoding": "gzip, br", "Range": "bytes=0-8"}) as response:
                body = await response.read()
                self.assertEqual(response.status, 200)
                self.assertEqual(body, (ROOT / "public" / file).read_bytes())
                self.assertEqual(response.content_type, content_type)
                self.assertEqual(int(response.headers["Content-Length"]), len(body))
                self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
                etag = response.headers["ETag"]
            async with self.client.get(self.server.make_url(f"/assets/{file}"),
                                       headers={"If-None-Match": etag}) as response:
                self.assertEqual(response.status, 304)
                self.assertEqual(await response.read(), b"")
                self.assertNotIn("Content-Length", response.headers)

    async def test_static_allowlist_does_not_expose_private_paths(self):
        for path in ["/assets/../server.py", "/assets/%2e%2e/server.py",
                     "/assets/%2e%2e%2fserver.py", "/assets/server.py",
                     "/assets/.git/config", "/assets/data/FERN.json",
                     "/assets/vendor/", "/assets/index.html"]:
            async with self.client.get(self.server.make_url(path)) as response:
                self.assertEqual(response.status, 404, path)

    async def test_two_clients_edit_sync_isolation_and_rejoin(self):
        a, welcome_a = await self.join("a" * 32)
        b, _ = await self.join("b" * 32)
        c, _ = await self.join("c" * 32, "TIDE")
        shared = await self.receive_type(b, "state")
        self.assertEqual(len(shared["players"]), 2)
        self.assertEqual(len((await self.receive_type(c, "state"))["players"]), 1)
        room = self.app[APP_STATE]["rooms"]["FERN"]
        room.players["a" * 32]["pos"] = [18.5, 8.05, 17.5]
        room.world.set(18, 9, 14, 4)
        room.world.set(18, 9, 13, 3)
        await a.send_json({"type": "input", "x": 0, "z": 0, "yaw": 0, "pitch": 0})
        await a.send_json({"type": "action", "action": "mine"})
        self.assertIn("collected", (await self.receive_type(a, "notice"))["text"])
        change_seen = False
        for _ in range(8):
            msg = await self.receive_type(b, "state")
            if [18, 9, 14, 0] in msg["changes"]:
                change_seen = True
                break
        self.assertTrue(change_seen, "Shared mining edit did not reach second client")
        self.assertEqual(count(room.players["a" * 32]["inv"], "log"), 7)
        await asyncio.sleep(.6)
        await a.send_json({"type": "action", "action": "place", "slot": 0})
        self.assertIn("placed", (await self.receive_type(a, "notice"))["text"])
        for _ in range(8):
            msg = await self.receive_type(b, "state")
            if [18, 9, 14, 2] in msg["changes"]:
                break
        else:
            self.fail("Shared placement did not reach second client")
        self.assertEqual(self.app[APP_STATE]["rooms"]["TIDE"].world.get(18, 9, 14), 0)
        saved_inv = copy.deepcopy(room.players["a" * 32]["inv"])
        await a.close()
        await asyncio.sleep(.15)
        _, rejoined = await self.join("a" * 32)
        self.assertEqual(rejoined["state"]["you"]["inv"], saved_inv)
        decoded = [b for i in range(0, len(rejoined["blocks"]), 2)
                   for b in [rejoined["blocks"][i]] * rejoined["blocks"][i + 1]]
        self.assertEqual(decoded[room.world.index(18, 9, 14)], 2)

    async def test_malformed_actions_report_error_not_disconnect(self):
        a, _ = await self.join("d" * 32)
        for payload in [
            {"type": "action", "action": "craft", "recipe": []},
            {"type": "input", "yaw": float("nan")},
            {"type": "action", "action": "place", "slot": -2},
            {"type": "action", "action": "teleport", "pos": [50, 50, 50]},
        ]:
            await a.send_json(payload)
            msg = await self.receive_type(a, "error")
            self.assertTrue(msg["text"])
        self.assertFalse(a.closed)

    async def test_reconnect_replaces_stale_socket_without_losing_scout(self):
        a, _ = await self.join("1" * 32)
        room = self.app[APP_STATE]["rooms"]["FERN"]
        add_items(room.players["1" * 32]["inv"], {"copper": 3})
        b = await self.client.ws_connect(self.server.make_url("/ws"))
        self.sockets.append(b)
        await b.send_json({"type": "join", "room": "FERN", "token": "1" * 32, "reconnect": True})
        msg = await b.receive_json(timeout=4)
        self.assertEqual(msg["type"], "welcome")
        self.assertEqual(count(msg["state"]["you"]["inv"], "copper"), 3)
        await asyncio.sleep(.2)
        self.assertTrue(room.players["1" * 32]["online"])
        self.assertEqual(len(self.app[APP_STATE]["connections"]), 1)
        await a.close()
        self.assertTrue(room.players["1" * 32]["online"])

    async def test_edit_during_broadcast_reaches_earlier_client_next_batch(self):
        a, _ = await self.join("2" * 32)
        b, _ = await self.join("3" * 32)
        state = self.app[APP_STATE]
        room = state["rooms"]["FERN"]
        room.players["3" * 32]["pos"] = [18.5, 8.05, 17.5]
        room.world.set(18, 9, 14, 4)
        server_socket = state["connections"][("FERN", "2" * 32)]
        original_send = server_socket.send_json
        entered = asyncio.Event()
        async def delay_after_send(msg, *args, **kwargs):
            await original_send(msg, *args, **kwargs)
            if msg["type"] == "state":
                entered.set()
                await asyncio.sleep(.2)
        server_socket.send_json = delay_after_send
        await asyncio.wait_for(entered.wait(), 3)
        await b.send_json({"type": "input", "x": 0, "z": 0, "yaw": 0, "pitch": 0})
        await b.send_json({"type": "action", "action": "mine"})
        self.assertIn("collected", (await self.receive_type(b, "notice"))["text"])
        for _ in range(8):
            update = await self.receive_type(a, "state")
            if [18, 9, 14, 0] in update["changes"]:
                break
        else:
            self.fail("An edit arriving during a broadcast was lost for its earlier client")
        server_socket.send_json = original_send

    async def test_chest_shared_and_movement_synced(self):
        a, _ = await self.join("e" * 32)
        b, _ = await self.join("f" * 32)
        room = self.app[APP_STATE]["rooms"]["FERN"]
        p = room.players["e" * 32]
        p["pos"] = [16.5, 8.05, 13.5]
        await a.send_json({"type": "input", "yaw": 0, "pitch": -.32, "x": 0, "z": 0})
        await a.send_json({"type": "action", "action": "open"})
        self.assertIn("Treasure", (await self.receive_type(a, "notice"))["text"])
        found = False
        for _ in range(6):
            update = await self.receive_type(b, "state")
            if update["chests"]["16,8,11"]:
                found = True
                break
        self.assertTrue(found)
        start = p["pos"][:]
        for _ in range(5):
            await a.send_json({"type": "input", "yaw": 0, "pitch": 0, "x": 1, "z": 0})
            await asyncio.sleep(.1)
        update = await self.receive_type(b, "state")
        for _ in range(6):
            remote = next(v for v in update["players"] if v["id"] == "e" * 32)
            if remote["pos"][0] > start[0] + .3:
                break
            update = await self.receive_type(b, "state")
        self.assertGreater(remote["pos"][0], start[0] + .3)


if __name__ == "__main__":
    unittest.main()
