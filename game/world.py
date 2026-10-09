import math
import random

SIZE = 64
HEIGHT = 28
SEA = 5
DAY_LENGTH = 420
DAY_FRACTION = 0.68
SLOTS = 12
STACK = 32
BLOCKS = {
    0: {"name": "Air", "solid": False},
    1: {"name": "Grass", "item": "dirt", "solid": True},
    2: {"name": "Earth", "item": "dirt", "solid": True},
    3: {"name": "Stone", "item": "stone", "solid": True},
    4: {"name": "Timber", "item": "log", "solid": True},
    5: {"name": "Leaves", "item": "leaf", "solid": True},
    6: {"name": "Water", "solid": False},
    7: {"name": "Sand", "item": "sand", "solid": True},
    8: {"name": "Copper", "item": "copper", "solid": True},
    9: {"name": "Planks", "item": "plank", "solid": True},
    10: {"name": "Treasure", "solid": True},
    11: {"name": "Lantern", "item": "lantern", "solid": True},
    12: {"name": "Keep beacon", "item": "beacon", "solid": True},
    13: {"name": "Bedrock", "solid": True},
}
ITEMS = {
    "dirt": {"name": "Earth", "block": 2},
    "stone": {"name": "Stone", "block": 3},
    "log": {"name": "Timber", "block": 4},
    "leaf": {"name": "Leaves", "block": 5},
    "sand": {"name": "Sand", "block": 7},
    "copper": {"name": "Copper", "block": 8},
    "plank": {"name": "Planks", "block": 9},
    "lantern": {"name": "Lantern", "block": 11},
    "beacon": {"name": "Keep beacon", "block": 12},
    "berry": {"name": "Berries", "food": 18, "heal": 5},
    "meat": {"name": "Raw meat", "food": 24, "heal": 3},
    "meal": {"name": "Trail meal", "food": 48, "heal": 22},
    "pick": {"name": "Stone pick", "limit": 1},
    "sword": {"name": "Copper sword", "limit": 1},
    "charm": {"name": "Warden charm", "limit": 1},
    "relic": {"name": "Wild relic"},
}
RECIPES = {
    "planks": {"name": "Cut planks", "cost": {"log": 1}, "out": {"plank": 4}},
    "pick": {"name": "Stone pick", "cost": {"log": 2, "stone": 3}, "out": {"pick": 1}},
    "sword": {"name": "Copper sword", "cost": {"plank": 2, "copper": 4}, "out": {"sword": 1}},
    "lantern": {"name": "Camp lanterns", "cost": {"plank": 2, "copper": 1}, "out": {"lantern": 3}},
    "meal": {"name": "Trail meal", "cost": {"berry": 3, "meat": 1}, "out": {"meal": 1}},
    "charm": {"name": "Warden charm", "cost": {"copper": 8, "stone": 6}, "out": {"charm": 1}},
    "beacon": {"name": "Keep beacon", "cost": {"relic": 3, "copper": 8, "plank": 12}, "out": {"beacon": 1}},
}


class RuleError(Exception):
    pass


def count(inv, item):
    return sum(s["count"] for s in inv if s and s["item"] == item)


def add_items(inv, items):
    """All-or-nothing insertion, including multiple loot stacks."""
    result = [dict(s) if s else None for s in inv]
    for item, amount in items.items():
        limit = ITEMS[item].get("limit", STACK)
        for slot in result:
            if slot and slot["item"] == item:
                n = min(amount, limit - slot["count"])
                slot["count"] += n
                amount -= n
        for i, slot in enumerate(result):
            if slot is None and amount:
                n = min(amount, limit)
                result[i] = {"item": item, "count": n}
                amount -= n
        if amount:
            raise RuleError("Pack full. Drop a stack in your pack, then try again.")
    inv[:] = result


def remove_items(inv, items):
    if any(count(inv, item) < amount for item, amount in items.items()):
        raise RuleError("Not enough supplies.")
    for item, amount in items.items():
        for i, slot in enumerate(inv):
            if slot and slot["item"] == item:
                n = min(amount, slot["count"])
                amount -= n
                slot["count"] -= n
                if slot["count"] == 0:
                    inv[i] = None


def craft(inv, recipe):
    if not isinstance(recipe, str) or recipe not in RECIPES:
        raise RuleError("Unknown recipe.")
    r = RECIPES[recipe]
    candidate = [dict(s) if s else None for s in inv]
    remove_items(candidate, r["cost"])
    add_items(candidate, r["out"])
    inv[:] = candidate


def is_night(clock):
    return (clock % DAY_LENGTH) / DAY_LENGTH >= DAY_FRACTION


def direction(yaw, pitch):
    return (-math.sin(yaw) * math.cos(pitch), math.sin(pitch),
            -math.cos(yaw) * math.cos(pitch))


def distance(a, b):
    return math.sqrt(sum((a[i] - b[i]) ** 2 for i in range(3)))


class World:
    def __init__(self, seed=741):
        self.seed = seed
        self.blocks = [0] * (SIZE * HEIGHT * SIZE)
        self.edits = {}
        self.chests = {}
        self.clock = 40.0
        self.won = False
        self.rng = random.Random(seed)
        self.generate()

    def index(self, x, y, z):
        return (y * SIZE + z) * SIZE + x

    def inside(self, x, y, z):
        return 0 <= x < SIZE and 0 <= y < HEIGHT and 0 <= z < SIZE

    def get(self, x, y, z):
        if not self.inside(x, y, z):
            return 13 if y < 0 or x < 0 or z < 0 or x >= SIZE or z >= SIZE else 0
        return self.blocks[self.index(x, y, z)]

    def solid(self, x, y, z):
        return BLOCKS[self.get(math.floor(x), math.floor(y), math.floor(z))]["solid"]

    def set(self, x, y, z, block, edit=False):
        if self.inside(x, y, z):
            i = self.index(x, y, z)
            self.blocks[i] = block
            if edit:
                self.edits[str(i)] = block

    def ground(self, x, z):
        # Terrain surface, ignoring tree canopies and structures.
        for y in range(HEIGHT - 1, -1, -1):
            if self.get(int(x), y, int(z)) in (1, 2, 3, 7, 8, 13):
                return y + 1
        return 1

    def generate(self):
        rng = self.rng
        for x in range(SIZE):
            for z in range(SIZE):
                h = round(7 + 1.3 * math.sin(x / 8) + 1.2 * math.cos(z / 9))
                lake = ((x - 44) / 10) ** 2 + ((z - 32) / 14) ** 2 < 1
                if lake:
                    h = 2 + int(((x - 44) ** 2 + (z - 32) ** 2) / 90)
                    h = min(4, h)
                if x < 3 or z < 3 or x > 60 or z > 60:
                    h = 2
                for y in range(max(h, SEA) + 1):
                    b = 13 if y == 0 else (3 if y < h - 2 else 2)
                    if y == h:
                        b = 7 if h < SEA or lake else 1
                    if 0 < y < h - 1 and rng.random() < 0.07:
                        b = 8
                    if y > h:
                        b = 6
                    self.set(x, y, z, b)
        # A broad open camp makes the first touch movement forgiving.
        for x in range(9, 19):
            for z in range(9, 19):
                for y in range(1, 13):
                    self.set(x, y, z, 1 if y == 7 else (2 if y < 7 else 0))
        for x in range(5, 60, 3):
            for z in range(5, 60, 3):
                if 7 <= x <= 20 and 7 <= z <= 20:
                    continue
                if rng.random() > 0.37:
                    continue
                y = self.ground(x, z)
                if y <= SEA + 1 or y > 11:
                    continue
                for dy in range(4):
                    self.set(x, y + dy, z, 4)
                for dx in range(-2, 3):
                    for dz in range(-2, 3):
                        for dy in range(3, 6):
                            if abs(dx) + abs(dz) < 4 and (dx or dz or dy >= 4):
                                self.set(x + dx, y + dy, z + dz, 5)
        for x, z, loot in [
            (16, 11, {"berry": 12, "copper": 4, "log": 8}),
            (28, 18, {"copper": 7, "meat": 4, "stone": 12}),
            (54, 33, {"meal": 3, "copper": 6}),
            (12, 48, {"berry": 12, "plank": 16}),
            (47, 53, {"meal": 4, "copper": 10}),
        ]:
            y = self.ground(x, z)
            self.set(x, y, z, 10)
            self.chests[f"{x},{y},{z}"] = {"loot": loot, "opened": False}
        for x, z in [(11, 11), (17, 17)]:
            self.set(x, 8, z, 11)
        # Exposed ore and stone outcrops, including one beside camp.
        for x, z in [(19, 13), (24, 26), (30, 45), (53, 50), (8, 38)]:
            y = self.ground(x, z)
            for dx in range(3):
                self.set(x + dx, y, z, 8 if dx == 1 else 3)

    def spawn(self):
        return [13.5, 8.05, 14.5]

    def collides(self, pos):
        x, y, z = pos
        for xx in (x - 0.29, x + 0.29):
            for yy in (y + 0.04, y + 0.85, y + 1.65):
                for zz in (z - 0.29, z + 0.29):
                    if self.solid(xx, yy, zz):
                        return True
        return False

    def ray(self, origin, vec, reach=5.5):
        previous = tuple(math.floor(c) for c in origin)
        for n in range(1, int(reach / 0.05) + 1):
            p = tuple(math.floor(origin[i] + vec[i] * n * 0.05) for i in range(3))
            b = self.get(*p)
            if BLOCKS[b]["solid"]:
                return p, previous, b
            previous = p
        return None

    def line_clear(self, start, end):
        length = distance(start, end)
        if length < 0.1:
            return True
        hit = self.ray(start, tuple((end[i] - start[i]) / length for i in range(3)), length)
        return hit is None

    def mine(self, player, hit):
        if not hit:
            raise RuleError("Aim at a block within reach.")
        p, _, block = hit
        if block in (10, 12, 13):
            raise RuleError("Use Open for treasure. Beacons and bedrock cannot be mined.")
        if block in (3, 8) and not count(player["inv"], "pick"):
            raise RuleError("Craft a stone pick to mine rock and copper.")
        if distance([p[0] + 0.5, p[1] + 0.5, p[2] + 0.5],
                    [player["pos"][0], player["pos"][1] + 1.5, player["pos"][2]]) > 6:
            raise RuleError("That block is too far away.")
        add_items(player["inv"], {BLOCKS[block]["item"]: 1})
        self.set(*p, 0, edit=True)
        return (*p, 0)

    def place(self, player, hit, slot, players):
        if not hit or not 0 <= slot < SLOTS or not player["inv"][slot]:
            raise RuleError("Select a block in your pack and aim at a nearby surface.")
        item = player["inv"][slot]["item"]
        block = ITEMS[item].get("block")
        if block is None:
            raise RuleError("This item is not a building block.")
        p = hit[1]
        if not self.inside(*p) or p[1] < 1 or self.get(*p) not in (0, 6):
            raise RuleError("There is no space to build here.")
        for other in players:
            x, y, z = other["pos"]
            if (p[0] < x + 0.3 and p[0] + 1 > x - 0.3 and
                    p[2] < z + 0.3 and p[2] + 1 > z - 0.3 and
                    p[1] < y + 1.7 and p[1] + 1 > y):
                raise RuleError("A scout is standing there.")
        remove_items(player["inv"], {item: 1})
        self.set(*p, block, edit=True)
        if block == 12:
            self.won = True
        return (*p, block)

    def open_chest(self, player, hit):
        if not hit or hit[2] != 10:
            raise RuleError("Aim at a treasure chest and tap Open.")
        key = ",".join(str(n) for n in hit[0])
        chest = self.chests[key]
        if chest["opened"]:
            raise RuleError("This chest is empty. Another scout may have opened it.")
        add_items(player["inv"], chest["loot"])
        chest["opened"] = True
        return chest["loot"]

    def encoded(self):
        runs = []
        last = self.blocks[0]
        n = 0
        for b in self.blocks:
            if b != last:
                runs.extend([last, n])
                last, n = b, 0
            n += 1
        runs.extend([last, n])
        return runs
