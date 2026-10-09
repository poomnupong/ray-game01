import math
import uuid

from .world import (BLOCKS, DAY_LENGTH, HEIGHT, ITEMS, SIZE, SLOTS, RuleError,
                    World, add_items, count, craft, direction, distance,
                    is_night, remove_items)

BOSSES = [
    ("thorn", "Thorn Colossus", 28, 48, 180, "Quake"),
    ("tide", "Tide Warden", 55, 29, 150, "Volley"),
    ("ember", "Ember Ram", 48, 52, 200, "Charge"),
]


def new_player(pid, world, number):
    inv = [None] * SLOTS
    add_items(inv, {"dirt": 24, "log": 6, "stone": 6, "berry": 10})
    return {"id": pid, "name": f"Scout {number}", "pos": world.spawn(),
            "yaw": math.pi, "pitch": -0.12, "hp": 100.0, "hunger": 100.0,
            "oxygen": 100.0, "inv": inv, "vy": 0.0, "grounded": False,
            "input": {"x": 0.0, "z": 0.0, "jump": False}, "input_at": 0.0,
            "cooldown": 0.0, "hurt": 0.0, "deaths": 0, "online": False}


class Room:
    def __init__(self, name, seed=741):
        self.name = name
        self.world = World(seed)
        self.players = {}
        self.mobs = []
        self.projectiles = []
        self.time = 0.0
        self.spawn_timer = 0.0
        self.changes = []
        self.events = []
        for i, kind in enumerate(["pig", "cow", "chicken", "horse", "deer", "fox",
                                  "pig", "cow", "chicken", "rabbit", "deer", "horse",
                                  "fox", "rabbit", "pig", "cow", "chicken", "deer"]):
            x, z = (18 + i * 7 % 38, 16 + i * 11 % 37)
            if i < 6:
                x, z = (10 + i * 2, 18 + i % 3)
            self.add_mob(kind, x, z)
        for kind, name, x, z, hp, attack in BOSSES:
            mob = self.add_mob(kind, x, z)
            mob.update(name=name, hp=hp, maxhp=hp, boss=True, awake=False,
                       attack=attack, windup=0.0, special=4.0)

    def add_mob(self, kind, x, z):
        mob = {"id": uuid.uuid4().hex[:10], "kind": kind, "name": kind.title(),
               "pos": [x + 0.5, self.world.ground(x, z), z + 0.5],
               "hp": 28 if kind in ("zombie", "skeleton") else 18,
               "maxhp": 28 if kind in ("zombie", "skeleton") else 18,
               "boss": False, "awake": False, "yaw": 0.0,
               "cooldown": 0.0, "wander": self.world.rng.random() * 6.28,
               "wander_timer": 0.0, "windup": 0.0}
        self.mobs.append(mob)
        return mob

    def public_player(self, p):
        return {k: p[k] for k in ("id", "name", "pos", "yaw", "pitch", "hp", "online")}

    def snapshot(self, pid):
        p = self.players[pid]
        return {"type": "state", "time": self.time, "clock": self.world.clock,
                "night": is_night(self.world.clock), "won": self.world.won,
                "players": [self.public_player(v) for v in self.players.values() if v["online"]],
                "you": {k: p[k] for k in ("pos", "hp", "hunger", "oxygen", "inv", "deaths")},
                "mobs": self.mobs, "projectiles": self.projectiles,
                "chests": {k: c["opened"] for k, c in self.world.chests.items()},
                "changes": self.changes, "events": self.events}

    def damage(self, p, amount):
        if p["hurt"] > 0:
            return
        if count(p["inv"], "charm"):
            amount *= 0.65
        p["hp"] -= amount
        p["hurt"] = 0.5
        if p["hp"] <= 0:
            p.update(pos=self.world.spawn(), hp=100.0, hunger=75.0,
                     oxygen=100.0, vy=0.0, deaths=p["deaths"] + 1)
            self.events.append({"text": f'{p["name"]} returned to camp. Pack kept.', "player": p["id"]})

    def tick_player(self, p, dt):
        p["cooldown"] = max(0, p["cooldown"] - dt)
        p["hurt"] = max(0, p["hurt"] - dt)
        x, y, z = p["pos"]
        water = self.world.get(math.floor(x), math.floor(y + 0.8), math.floor(z)) == 6
        underwater = self.world.get(math.floor(x), math.floor(y + 1.5), math.floor(z)) == 6
        inp = p["input"] if self.time - p["input_at"] < 0.5 else {"x": 0, "z": 0, "jump": False}
        speed = 2.6 if water else 4.4
        sx, sz = inp["x"], inp["z"]
        mag = max(1, math.hypot(sx, sz))
        sx, sz = sx / mag, sz / mag
        dx = (math.cos(p["yaw"]) * sx - math.sin(p["yaw"]) * sz) * speed * dt
        dz = (-math.sin(p["yaw"]) * sx - math.cos(p["yaw"]) * sz) * speed * dt
        if water:
            p["vy"] += (7 if inp["jump"] else -2.4) * dt
            p["vy"] *= max(0, 1 - dt * 2)
            p["vy"] = min(3.3, max(-2, p["vy"]))
        else:
            if inp["jump"] and p["grounded"]:
                p["vy"] = 7.5
            p["vy"] -= 20 * dt
        for axis, delta in ((0, dx), (2, dz)):
            next_pos = p["pos"][:]
            next_pos[axis] += delta
            if not self.world.collides(next_pos):
                p["pos"] = next_pos
            elif p["grounded"]:
                next_pos[1] += 1.01
                if not self.world.collides(next_pos):
                    p["pos"] = next_pos
        delta = p["vy"] * dt
        p["grounded"] = False
        # Small substeps prevent tunnelling through voxel floors.
        steps = max(1, math.ceil(abs(delta) / 0.15))
        for _ in range(steps):
            next_pos = p["pos"][:]
            next_pos[1] += delta / steps
            if self.world.collides(next_pos):
                p["grounded"] = delta < 0
                if p["vy"] < -13 and not water:
                    self.damage(p, abs(p["vy"]) - 9)
                p["vy"] = 0
                break
            p["pos"] = next_pos
        p["oxygen"] = max(0, p["oxygen"] - 12 * dt) if underwater else min(100, p["oxygen"] + 35 * dt)
        if p["oxygen"] == 0:
            self.damage(p, 6)
        p["hunger"] = max(0, p["hunger"] - dt * (0.10 if mag == 1 and sx == 0 and sz == 0 else 0.20))
        if p["hunger"] == 0:
            self.damage(p, 2)
        elif p["hunger"] > 65:
            p["hp"] = min(100, p["hp"] + dt * 0.8)
        if p["pos"][1] < -2:
            self.damage(p, 200)

    def move_mob(self, m, dx, dz):
        x, y, z = m["pos"]
        nx, nz = min(60.5, max(3.5, x + dx)), min(60.5, max(3.5, z + dz))
        # Use actual solid ground: player walls obstruct mobs, roof heights do not teleport them.
        floor = math.floor(y)
        candidates = [floor, floor + 1, floor - 1, floor - 2]
        for ny in candidates:
            if ny < 1:
                continue
            if (self.world.solid(nx, ny - 0.1, nz) and
                    not self.world.solid(nx, ny + 0.1, nz) and
                    not self.world.solid(nx, ny + 1.1, nz)):
                m["pos"] = [nx, float(ny), nz]
                if abs(dx) + abs(dz) > 0.001:
                    m["yaw"] = math.atan2(-dx, -dz)
                return

    def shoot(self, m, p, damage=9, speed=8):
        origin = [m["pos"][0], m["pos"][1] + 1.4, m["pos"][2]]
        end = [p["pos"][0], p["pos"][1] + 0.8, p["pos"][2]]
        d = max(0.1, distance(origin, end))
        self.projectiles.append({"id": uuid.uuid4().hex[:8], "pos": origin,
                                 "vel": [(end[i] - origin[i]) * speed / d for i in range(3)],
                                 "life": 4.0, "damage": damage})

    def tick_mobs(self, dt, players):
        for m in self.mobs[:]:
            if m["hp"] <= 0:
                continue
            m["cooldown"] = max(0, m["cooldown"] - dt)
            hostile = m["kind"] in ("zombie", "skeleton") or (m["boss"] and m["awake"])
            if not hostile or not players:
                if m["boss"]:
                    continue
                m["wander_timer"] -= dt
                if m["wander_timer"] <= 0:
                    m["wander_timer"] = 3 + self.world.rng.random() * 5
                    m["wander"] = self.world.rng.random() * 6.28
                self.move_mob(m, math.sin(m["wander"]) * dt * 0.5,
                              math.cos(m["wander"]) * dt * 0.5)
                continue
            p = min(players, key=lambda q: distance(q["pos"], m["pos"]))
            d = distance(p["pos"], m["pos"])
            if d > 23:
                continue
            delta = [p["pos"][i] - m["pos"][i] for i in range(3)]
            visible = self.world.line_clear([m["pos"][0], m["pos"][1] + 1.3, m["pos"][2]],
                                            [p["pos"][0], p["pos"][1] + 1.2, p["pos"][2]])
            if m["boss"]:
                m["special"] -= dt
                if m["windup"] > 0:
                    m["windup"] -= dt
                    if m["windup"] <= 0:
                        if m["kind"] == "thorn":
                            for victim in players:
                                clear = self.world.line_clear(
                                    [m["pos"][0], m["pos"][1] + 1.3, m["pos"][2]],
                                    [victim["pos"][0], victim["pos"][1] + 1.2, victim["pos"][2]])
                                if distance(victim["pos"], m["pos"]) < 6 and clear:
                                    self.damage(victim, 26)
                        elif m["kind"] == "tide":
                            for victim in players:
                                if distance(victim["pos"], m["pos"]) < 18:
                                    self.shoot(m, victim, 18, 11)
                        else:
                            m["charge"] = 1.2
                        m["special"] = 5.0
                    continue
                if m["special"] <= 0:
                    m["windup"] = 1.4
                    continue
            speed = 1.6 if m["kind"] == "zombie" else 1.1
            if m.get("charge", 0) > 0:
                speed = 7
                m["charge"] -= dt
            if d > (6 if m["kind"] == "skeleton" else 1.5):
                self.move_mob(m, delta[0] / max(d, 0.1) * speed * dt,
                              delta[2] / max(d, 0.1) * speed * dt)
            if m["cooldown"] <= 0 and visible:
                if m["kind"] == "skeleton" and d < 14:
                    self.shoot(m, p)
                    m["cooldown"] = 2.5
                elif d < (2.5 if m["boss"] else 1.9):
                    self.damage(p, 16 if m["boss"] else 8)
                    m["cooldown"] = 1.2

    def tick(self, dt):
        self.time += dt
        players = [p for p in self.players.values() if p["online"]]
        if not players:
            return
        was_night = is_night(self.world.clock)
        self.world.clock += dt
        night = is_night(self.world.clock)
        if was_night != night:
            self.events.append({"text": "Nightfall. Build shelter; the restless are coming." if night
                                else "Dawn. The forest is peaceful again."})
            if not night:
                self.mobs[:] = [m for m in self.mobs if m["kind"] not in ("zombie", "skeleton")]
        for p in players:
            self.tick_player(p, dt)
        self.spawn_timer -= dt
        if night and self.spawn_timer <= 0:
            self.spawn_timer = 9
            hostiles = [m for m in self.mobs if m["kind"] in ("zombie", "skeleton")]
            if len(hostiles) < 14:
                p = self.world.rng.choice(players)
                angle = self.world.rng.random() * 6.28
                x = min(59, max(4, p["pos"][0] + math.cos(angle) * 13))
                z = min(59, max(4, p["pos"][2] + math.sin(angle) * 13))
                self.add_mob(self.world.rng.choice(["zombie", "skeleton"]), int(x), int(z))
        self.tick_mobs(dt, players)
        for b in self.projectiles[:]:
            b["life"] -= dt
            b["pos"] = [b["pos"][i] + b["vel"][i] * dt for i in range(3)]
            hit = self.world.solid(*b["pos"])
            for p in players:
                center = [p["pos"][0], p["pos"][1] + 0.8, p["pos"][2]]
                if distance(center, b["pos"]) < 0.75:
                    self.damage(p, b["damage"])
                    hit = True
            if hit or b["life"] <= 0:
                self.projectiles.remove(b)

    def action(self, pid, msg):
        p = self.players[pid]
        action = msg.get("action")
        if p["cooldown"] > 0:
            raise RuleError("Wait a moment before your next action.")
        if action == "craft":
            craft(p["inv"], msg.get("recipe"))
            p["cooldown"] = 0.2
            return "Crafted. Your pack has been updated."
        if action == "give":
            slot = msg.get("slot")
            target = msg.get("target")
            if type(slot) is not int or not 0 <= slot < SLOTS or p["inv"][slot] is None:
                raise RuleError("Select a filled pack slot.")
            if not isinstance(target, str) or target == pid or target not in self.players:
                raise RuleError("Choose another nearby scout.")
            other = self.players[target]
            if not other["online"] or distance(p["pos"], other["pos"]) > 6:
                raise RuleError("Move within 6 blocks of that scout to share supplies.")
            stack = p["inv"][slot]
            add_items(other["inv"], {stack["item"]: stack["count"]})
            p["inv"][slot] = None
            p["cooldown"] = 0.2
            self.events.append({"text": f'{p["name"]} gave you {stack["count"]} {ITEMS[stack["item"]]["name"]}.',
                                "player": target})
            return f'Stack given to {other["name"]}.'
        if action in ("eat", "drop"):
            slot = msg.get("slot")
            if type(slot) is not int or not 0 <= slot < SLOTS or p["inv"][slot] is None:
                raise RuleError("Select a filled pack slot.")
            stack = p["inv"][slot]
            if action == "drop":
                p["inv"][slot] = None
                return "Stack discarded."
            item = ITEMS[stack["item"]]
            if "food" not in item:
                raise RuleError("Select berries, meat, or a trail meal to eat.")
            remove_items(p["inv"], {stack["item"]: 1})
            p["hunger"] = min(100, p["hunger"] + item["food"])
            p["hp"] = min(100, p["hp"] + item["heal"])
            p["cooldown"] = 0.3
            return "Food eaten."
        if action == "gather":
            if self.world.get(int(p["pos"][0]), int(p["pos"][1] - 0.1), int(p["pos"][2])) != 1:
                raise RuleError("Stand on forest grass to forage.")
            add_items(p["inv"], {"berry": 1})
            p["cooldown"] = 3
            return "Found a berry. Forage again in 3 seconds."
        origin = [p["pos"][0], p["pos"][1] + 1.5, p["pos"][2]]
        vec = direction(p["yaw"], p["pitch"])
        hit = self.world.ray(origin, vec)
        if action == "mine":
            candidates = []
            for m in self.mobs:
                if m["hp"] <= 0:
                    continue
                center = [m["pos"][0], m["pos"][1] + (1.4 if m["boss"] else 0.65), m["pos"][2]]
                d = distance(origin, center)
                v = [center[i] - origin[i] for i in range(3)]
                along = sum(v[i] * vec[i] for i in range(3))
                off = math.sqrt(max(0, d * d - along * along))
                if 0 < along < 4.8 and off < (1.4 if m["boss"] else 0.8) and self.world.line_clear(origin, center):
                    candidates.append((d, m))
            if candidates:
                _, m = min(candidates, key=lambda pair: pair[0])
                damage = 22 if count(p["inv"], "sword") else 7
                if m["hp"] <= damage:
                    loot = {"relic": 1, "copper": 4, "meal": 2} if m["boss"] else (
                        {"copper": 1} if m["kind"] in ("zombie", "skeleton") else {"meat": 2})
                    add_items(p["inv"], loot)
                    self.events.append({"text": f'{p["name"]} defeated {m["name"]}.'})
                m["hp"] = max(0, m["hp"] - damage)
                if m["boss"]:
                    m["awake"] = True
                p["cooldown"] = 0.5
                return f'{m["name"]}: {math.ceil(m["hp"])} health'
            change = self.world.mine(p, hit)
            self.changes.append(change)
            p["cooldown"] = 0.25 if count(p["inv"], "pick") else 0.55
            return "Block collected."
        if action == "place":
            slot = msg.get("slot")
            if type(slot) is not int:
                raise RuleError("Select a building block first.")
            change = self.world.place(p, hit, slot, [q for q in self.players.values() if q["online"]])
            self.changes.append(change)
            p["cooldown"] = 0.25
            return "The keep beacon is lit. You restored Wildwood!" if self.world.won else "Block placed."
        if action == "open":
            loot = self.world.open_chest(p, hit)
            p["cooldown"] = 0.3
            return "Treasure: " + ", ".join(f"{n} {ITEMS[k]['name']}" for k, n in loot.items())
        raise RuleError("Unknown action.")
