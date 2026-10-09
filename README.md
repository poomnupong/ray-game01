# Wildwood Keep

A working, original tablet-first voxel survival game. Explore a forest island with
friends, mine resources, craft tools, swim, build a shelter, survive the night, and
defeat three wild wardens to restore the keep.

**No keyboard, account, Node, build step, or CDN is required to play.** The Python
server owns the world; the browser renders it with a locally bundled Three.js.
This is a local-network first playable prototype, not a hosted service.

## Start

From this repository, using Python 3.10+ (verified with Python 3.12):

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
./run.sh
```

The prepared environment in this checkout is already installed. Just run
`./run.sh`, or `.venv/bin/python server.py`, if the server is not already running.
If using `uv` to create the environment, `uv venv .venv` followed by
`.venv/bin/python -m ensurepip` enables the same pip installation commands.

Open **http://localhost:8080**. Choose FERN, TIDE, or EMBER, then tap **Enter the
wild**. The first visit opens a field guide. Use `?` to reopen it at any time.

Optional host settings:

```sh
./run.sh --host 0.0.0.0 --port 8080 --data ./data
```

The default binds to all network interfaces. Use `--host 127.0.0.1` for
computer-only play. Stop a foreground server with **Ctrl+C**; this saves the
loaded rooms. If started detached, stop its specific process with `kill PID`
(the launcher reports the PID), not a broad process-name kill.

## Two tablets on the same Wi-Fi

1. Keep the server running on the host computer. Connect the computer and tablets
   to the same Wi-Fi network.
2. Find the computer's **Wi-Fi IP address** in macOS System Settings → Wi-Fi →
   Details → TCP/IP. On this machine at implementation time it was
   **192.168.86.184**, so the tablet address was **http://192.168.86.184:8080**.
   DHCP can change this address. Do **not** enter localhost on a different device.
3. Open that address in Safari or Chrome on each tablet. Select the **same camp**.
   The three camps are independent copies of the same forest island, not three
   different biomes. Each supports up to **8 connected scouts**.

Allow Python's incoming local-network connections if the host firewall asks.
Guest Wi-Fi/client isolation, VPN routing, or a firewall can block device-to-device
traffic. `/health` shows server readiness and active scout count. No external
internet connection is needed after dependency installation.

### If `/health` works but the game reports an invalid HTTP response

Retry the fresh game entry **http://192.168.86.184:8080/play?v=2**, replacing the IP
if the host's Wi-Fi address has changed. `/play` serves the same real game as `/`,
with uncached HTML; it is not a diagnostic page. Keep the explicit **http://**
scheme: this local server does not support HTTPS.

HTML and the allowlisted game assets now use ordinary buffered HTTP responses,
not operating-system `sendfile`. The small asset set is cached in server memory;
JavaScript/CSS have explicit MIME types and ETag revalidation. HTML always returns
a complete 200 response, including when a browser sends stale cache or range
headers. The health JSON and response headers identify this delivery version as
`buffered-v2`. Restart the server after modifying a public asset.

This avoids a suspected difference between `/health` and native file delivery;
it does **not** establish the cause of an inaccessible tablet's browser error.
When health succeeds on that tablet, its HTTP/LAN path is already working:
do not disable the Mac firewall. The server now logs HTTP paths/statuses to help
diagnose any remaining delivery problem.

Every browser profile receives a random scout identity, stored locally. Use
different devices or profiles for different scouts; two tabs in one profile share
an identity. A broken connection retries automatically and can replace its own
stale socket. The HUD shows disconnects; input stops when disconnected, backgrounded,
or when a modal is open. The shared simulation continues while somebody is online.

## Play

| Action | Touch control |
|---|---|
| Move | Left-thumb joystick |
| Look | Drag an empty part of the world with the other thumb |
| Mine or attack | Aim the crosshair and tap/hold **Strike** |
| Build | Select a block in Pack/quick slots; aim at a surface; tap/hold **Build** |
| Jump or swim up | Hold **Rise** |
| Loot | Aim at a golden chest; tap **Open** |
| Eat | Select food in **Pack**, then **Eat one** |
| Gather berries | Stand on grass and tap **Forage** (3-second cooldown) |
| Craft | Open **Craft**; recipes show real costs and available supplies |
| Share a stack | Select it in Pack and **Give to Scout…**, within 6 blocks |

Multi-touch joystick, look, and rise/action inputs have independent pointer
tracking and capture. All room selection, menus, crafting, sharing, and gameplay
are usable without typing. Desktop players may use WASD and Space, with mouse-drag
look and the same visible action buttons.

Start with earth, timber, stone, and berries. Craft a **stone pick** to mine rock
and copper, cut timber into **planks**, and craft a **copper sword**. Carried tools
work automatically. Chests and animals provide additional supplies and food.
Build walls before night: zombies chase scouts and skeletons shoot arrows.
Water slows movement, allows swimming, and consumes air when submerged. Food
restores hunger and health; good hunger slowly heals. Falls, starvation, drowning,
and attacks can hurt. Death returns you to camp **with your pack kept**.

The inventory has **12 slots**, a **32-item stack cap**, and one tool per slot.
Crafting, treasure, sharing, and boss loot are all-or-nothing transactions. A full
pack does not consume costs or empty a chest. Discarding a stack permanently deletes
it; there are no dropped-item pickups.

### Forest discoveries and the shared goal

Coordinates are shown at the bottom right as **x, z**. Camp is near **13, 14**.
The starter chest is at **16, 11**, and an exposed copper outcrop is at **20, 13**.
Other chests are at **28, 18**, **54, 33**, **12, 48**, and **47, 53**.

Pigs, cows, chickens, horses, deer, foxes, and rabbits wander during the day.
Bosses are dormant until struck, so daytime exploration is peaceful:

| Warden | Territory | Special attack |
|---|---|---|
| Thorn Colossus | 28, 48 | A telegraphed six-block quake; leave the red ring |
| Tide Warden | 55, 29 | A telegraphed arrow volley toward nearby scouts |
| Ember Ram | 48, 52 | A telegraphed fast charge |

Every boss drops one wild relic, copper, and meals. Pool relics with friends using
Pack's **Give** action. Craft a **Keep beacon** with 3 relics, 8 copper, and 12
planks; place it to complete the shared room goal. A copper-and-stone charm reduces
damage without consuming a relic. Building and exploring can continue after victory.

## Persistence and honest limits

- Atomic JSON save files in ignored `data/` hold each room's block edits, chests,
  clock, victory, mobs/boss health, and saved scout packs/positions. Saves happen
  every 10 seconds, on disconnect, and on graceful server shutdown. A power loss
  may lose the last 10 seconds. Back up `data/` to keep your worlds.
- Unoccupied rooms pause their clock. Each cycle is **7 minutes**, with about
  **4 minutes 46 seconds of day** and **2 minutes 14 seconds of night**.
- The island is **64 × 64 × 28 blocks** with chunked, exposed-face terrain,
  frustum culling, capped pixel ratio, and lightweight original voxel models.
  It is bounded, not infinite; water has no fluid simulation and placed earth
  does not grow grass. No riding, pets, farming, PvP, audio, chat, or authentication.
- Bosses do not respawn, animals do not reproduce, and each chest is shared
  one-time loot. Each room permits 128 saved scout identities. Relics are finite:
  intentionally discarding them can make the beacon goal impossible in that room.
  Choose another camp for a fresh island, or stop the server and rename that
  specific room's save file to archive/reset it.
- Server-owned physics, range/aim, cooldowns, inventory, costs, block occupancy,
  chest ownership, and combat prevent ordinary client-side state spoofing.
  This is **not an internet-hardened service**: scout IDs are bearer identities,
  there is no login/TLS, and nearby players can mine one another's structures.
  Do not port-forward or expose the server to the public internet.
- Browser interpolation hides some 10 Hz snapshots, but movement is authoritative,
  not client-predicted. Slow Wi-Fi may feel laggy. The server simulates at roughly
  20 Hz; overloaded hosts slow the simulation rather than tunnelling through blocks.
- Automated tablet testing uses Chromium touch emulation, **not a physical iPad**.
  Safari/iPad hardware performance remains to be verified. WebGL is required.
  UI uses visible labels, focus states, and large buttons, but the 3D game itself
  is not a screen-reader-accessible experience.

## Tests

No JavaScript build or type-check step is needed: this client uses native ES
modules, and Python owns all shared gameplay rules.

```sh
.venv/bin/python -m unittest discover -v
.venv/bin/python -m compileall -q server.py game tests
```

The automated suite covers inventory overflow/stack limits, every recipe,
crafting atomicity, mining and tool requirements, block placement and occupancy,
one-time chest loot, cooperative relic sharing, beacon victory, swimming/air,
day/night spawning, bosses, save/reload, invalid packets, room isolation,
two-client movement/block/chest synchronization, and stale-socket reconnect.

For real browser smoke tests:

```sh
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m playwright install chromium
.venv/bin/python tests/browser_smoke.py
```

This starts a temporary isolated server and two separate tablet browser profiles
(1024×768 and 768×1024). It uses actual touch events for simultaneous joystick,
look and rise; visible controls for crafting/mining/placement/food; checks edits
on the second client; interrupts a WebSocket and verifies reconnection; checks
control bounds/overlap, rendering, and browser errors. Screenshots go to ignored
`test-results/`. Optional: `--url http://localhost:8080` targets an existing server
and changes its world; `--output /path` changes screenshot output.

## Source map and third-party notices

- `server.py`: HTTP/WebSocket hosting, packet validation, rooms, persistence.
- `game/world.py`: deterministic terrain, voxel rays, catalog, transactional inventory.
- `game/simulation.py`: movement, survival, shared mobs, combat, crafting/sharing actions.
- `public/renderer.js`: exposed-face chunk geometry, original creature models, lighting.
- `public/controls.js`: pointer-separated multi-touch and optional desktop inputs.
- `public/client.js`: connection lifecycle, HUD, pack/crafting and field guide.
- `tests/`: unit/network tests and browser smoke runner.

The art, world, names, models, and game code are original. Three.js **0.179.1**
is vendored unmodified in `public/vendor/`; its MIT license is included there as
`THREE-LICENSE.txt`. Runtime networking uses aiohttp (Apache-2.0); optional browser
tests use Playwright (Apache-2.0). No Minecraft artwork, textures, names, or branding
are included. Publishing this source repository does not deploy the game:
multiplayer still requires a running Python server, and the current prototype
is intended for trusted local-network play.
