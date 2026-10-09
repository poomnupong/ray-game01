"""Real Chromium touch/multiplayer smoke test; starts an isolated temporary world."""
import argparse
import json
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import urllib.request
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]


def assert_no_control_overlap(page):
    boxes = page.evaluate("""() => {
      const selectors=['#joystick','.actions','#hotbar','.utility'];
      return selectors.map(s=>{const r=document.querySelector(s).getBoundingClientRect();
        return {s,x:r.x,y:r.y,w:r.width,h:r.height};});
    }""")
    for a in boxes:
        assert a["x"] >= 0 and a["y"] >= 0, a
        assert a["x"] + a["w"] <= page.viewport_size["width"] + 1, a
        assert a["y"] + a["h"] <= page.viewport_size["height"] + 1, a
    for i, a in enumerate(boxes):
        for b in boxes[i + 1:]:
            overlap = (a["x"] < b["x"] + b["w"] and a["x"] + a["w"] > b["x"] and
                       a["y"] < b["y"] + b["h"] and a["y"] + a["h"] > b["y"])
            assert not overlap, f"Controls overlap: {a['s']} / {b['s']}"


def touch(cdp, kind, points):
    cdp.send("Input.dispatchTouchEvent", {"type": kind, "touchPoints": [
        {"id": i, "x": x, "y": y, "radiusX": 8, "radiusY": 8, "force": 1}
        for i, x, y in points]})


def run(url, output):
    errors = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True, args=[
            "--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"])
        contexts = [browser.new_context(viewport=v, has_touch=True, device_scale_factor=1)
                    for v in [{"width": 1024, "height": 768}, {"width": 768, "height": 1024}]]
        pages = [c.new_page() for c in contexts]
        transports = []
        def proxy(ws):
            upstream = ws.connect_to_server()
            transports.append((ws, upstream))
        pages[0].route_web_socket("**/ws", proxy)
        for i, page in enumerate(pages):
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on("console", lambda e: errors.append(e.text) if e.type == "error" else None)
            page.goto(url if i == 0 else urljoin(url, "/play?v=2"))
            page.wait_for_function("window.wildwood && window.wildwood.view")
        pages[0].screenshot(path=str(output / "lobby-landscape.png"))
        pages[1].screenshot(path=str(output / "lobby-portrait.png"))
        for page in pages:
            page.locator("#play").tap()
            page.wait_for_function("window.wildwood.connected", timeout=15000)
            page.locator("#close-panel").tap()
        for page in pages:
            page.wait_for_function("window.wildwood.state.players.length===2", timeout=10000)
            assert_no_control_overlap(page)
        a, b = pages
        start = a.evaluate("window.wildwood.state.you.pos")
        start_yaw = a.evaluate("window.wildwood.controls.yaw")
        cdp = contexts[0].new_cdp_session(a)
        rect = a.locator("#joystick").bounding_box()
        jx, jy = rect["x"] + rect["width"]/2, rect["y"] + rect["height"]/2
        touch(cdp, "touchStart", [(1, jx, jy)])
        touch(cdp, "touchStart", [(1, jx, jy), (2, 720, 380)])
        touch(cdp, "touchMove", [(1, jx+40, jy), (2, 775, 390)])
        a.wait_for_timeout(550)
        simultaneous = a.evaluate("""() => ({x:wildwood.controls.move.x,
              yaw:wildwood.controls.yaw, pos:wildwood.state.you.pos})""")
        assert simultaneous["x"] > .5, simultaneous
        assert abs(simultaneous["yaw"] - start_yaw) > .2, simultaneous
        assert abs(simultaneous["pos"][0] - start[0]) > .5, simultaneous
        touch(cdp, "touchEnd", [])
        a.wait_for_timeout(200)
        assert a.evaluate("wildwood.controls.move.x===0 && wildwood.controls.look===null")
        assert b.evaluate("wildwood.state.players.length") == 2
        # Simultaneously held joystick, world-look, and swim/jump button.
        jr = a.locator("#jump").bounding_box()
        touch(cdp, "touchStart", [(1,jx,jy),(2,700,380),(3,jr["x"]+20,jr["y"]+20)])
        a.wait_for_timeout(100)
        assert a.evaluate("wildwood.controls.jump && wildwood.controls.look!==null && wildwood.controls.joy!==null")
        touch(cdp, "touchEnd", [])
        a.wait_for_timeout(100)
        assert not a.evaluate("wildwood.controls.jump")
        # Craft a real tool with the seeded supplies, using only visible controls.
        a.locator("#craft").tap()
        a.locator('[data-recipe="pick"]').tap()
        a.wait_for_function("wildwood.state.you.inv.some(s=>s?.item==='pick')")
        assert a.evaluate("wildwood.state.you.inv.filter(s=>s?.item==='stone').reduce((n,s)=>n+s.count,0)") == 3
        a.locator("#close-panel").tap()
        # Touch-look downward, then mine terrain and verify the remote client's geometry.
        pitch_before = a.evaluate("wildwood.controls.pitch")
        touch(cdp, "touchStart", [(2,700,300)])
        touch(cdp, "touchMove", [(2,700,300+(pitch_before+1.1)/.006)])
        touch(cdp, "touchEnd", [])
        a.wait_for_timeout(200)
        hit = a.evaluate("""() => {let w=wildwood, p=w.state.you.pos;
          return w.view.ray(w.controls.yaw,w.controls.pitch,[p[0],p[1]+1.5,p[2]]);}""")
        assert hit and hit["block"] in [1,2,3,4,5,7,8], hit
        old_count = a.evaluate("wildwood.state.you.inv.filter(s=>s?.item==='dirt').reduce((n,s)=>n+s.count,0)")
        a.locator("#mine").tap()
        x, y, z = hit["pos"]
        a.wait_for_function(f"wildwood.view.get({x},{y},{z})===0")
        b.wait_for_function(f"wildwood.view.get({x},{y},{z})===0")
        assert a.evaluate("wildwood.state.you.inv.filter(s=>s?.item==='dirt').reduce((n,s)=>n+s.count,0)") > old_count
        # Placement uses a real stack and synchronizes through the server.
        a.locator('#hotbar [data-slot="0"]').tap()
        a.wait_for_timeout(650)
        # Build farther ahead, not in the mined hole beneath the scout's feet.
        pitch_now = a.evaluate("wildwood.controls.pitch")
        touch(cdp, "touchStart", [(2,700,450)])
        touch(cdp, "touchMove", [(2,700,450+(pitch_now+.5)/.006)])
        touch(cdp, "touchEnd", [])
        a.wait_for_timeout(200)
        placement = a.evaluate("""() => {let w=wildwood, p=w.state.you.pos;
          return w.view.ray(w.controls.yaw,w.controls.pitch,[p[0],p[1]+1.5,p[2]]);}""")
        assert placement, "No placement surface after mining"
        px, py, pz = placement["prev"]
        a.locator("#place").tap()
        try:
            a.wait_for_function(f"wildwood.view.get({px},{py},{pz})===2", timeout=4000)
        except Exception:
            print("Placement diagnostic", a.evaluate("""() => ({
              pos:wildwood.state.you.pos,inv:wildwood.state.you.inv,
              toast:document.querySelector('#toast').textContent})"""), placement)
            raise
        b.wait_for_function(f"wildwood.view.get({px},{py},{pz})===2")
        # Pack food action and expanded finite inventory.
        a.locator("#pack").tap()
        a.locator('.pack-slot[data-slot="3"]').tap()
        assert a.locator(".pack-slot").count() == 12
        a.locator("#eat").tap()
        a.wait_for_timeout(500)
        a.locator("#close-panel").tap()
        # Force a transport reconnect, not a page reload.
        client_transport, server_transport = transports[-1]
        server_transport.close(code=1001, reason="Smoke test network interruption")
        client_transport.close(code=1001, reason="Smoke test network interruption")
        a.wait_for_function("!wildwood.connected", timeout=10000)
        a.wait_for_function("wildwood.connected", timeout=15000)
        a.wait_for_function("wildwood.state.you.inv.some(s=>s?.item==='pick')")
        # Final batched visual evidence on both tablet orientations.
        for label, page in zip(["landscape", "portrait"], pages):
            assert_no_control_overlap(page)
            page.screenshot(path=str(output / f"game-{label}.png"))
            stats = page.evaluate("""() => ({drawCalls:wildwood.view.renderer.info.render.calls,
              triangles:wildwood.view.renderer.info.render.triangles,
              canvas:[document.querySelector('canvas').width,document.querySelector('canvas').height]})""")
            assert stats["triangles"] > 1000, stats
            print(label, json.dumps(stats))
        assert not errors, errors
        browser.close()
    print("PASS: two networked clients; landscape/portrait; simultaneous touch movement/look/rise;"
          " crafting; mining; shared placement; inventory/food; reconnect; no browser errors.")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", help="Test an existing server instead of a temporary one")
    parser.add_argument("--output", default=str(ROOT / "test-results"))
    args = parser.parse_args()
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.url:
        run(args.url, output)
        return
    with tempfile.TemporaryDirectory() as tmp:
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        proc = subprocess.Popen([sys.executable, str(ROOT / "server.py"), "--host", "127.0.0.1",
                                 "--port", str(port), "--data", tmp], stdout=subprocess.DEVNULL)
        try:
            url = f"http://127.0.0.1:{port}"
            for _ in range(60):
                try:
                    urllib.request.urlopen(url + "/health", timeout=.5).close()
                    break
                except OSError:
                    if proc.poll() is not None:
                        raise RuntimeError("Temporary server failed to start")
                    time.sleep(.1)
            else:
                raise RuntimeError("Temporary server never became ready")
            run(url, output)
        finally:
            proc.terminate()
            proc.wait(timeout=10)


if __name__ == "__main__":
    main()
