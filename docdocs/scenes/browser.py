"""Browser scenes: the real product, in the real browser.

    {"type": "browser", "system": "demo", "checkout": "before", "network": "slow-4g",
     "device": "phone", "overlay": ["layout-shift"], "holdShifts": true, "badge": "before · Slow 4G",
     "beats": [{"say": "...", "label": "the page *jumps*", "do": [{"goto": "/products"}, {"waitFor": "main[data-state=loaded]"}]}]}

checkout    a git ref to build and serve first (optional; else the working tree)
start       a path to open before the scene fades in, so it fades in on that
            page rather than on a blank one
network     a profile from docdocs.network (optional)
device      "phone": in a landscape format, the page plays at phone width inside
            a phone frame on the brand canvas, with a big live layout-shift
            counter beside it. Portrait formats are phone-shaped already.
overlay     "layout-shift" outlines every element that moves, with a running CLS
holdShifts  keep the outlines until a clearShifts action, so the narration can
            point at them
badge       a label in the corner; badgeColor "before" (amber) or "after" (cyan)

Actions: goto, waitFor, scroll, click, type, select, press, reload,
clearShifts, and the common wait, zoom, unzoom and label.
{"click": "<selector>", "instant": true} fires the click event at once instead
of moving the mouse there first, so it lands on its word.
{"type": "<selector>", "text": "..."} clicks the field and types the text one
key at a time, as a person would; "delay" is the gap between keys in ms
(default 45). {"select": "<selector>", "value": "..."} picks an option of a
<select> by its value or its label. {"press": "Enter"} presses one key, or a
chord such as "Control+A", wherever the focus is. Labels get a navy backdrop
here, so they read on any page.
"""

import asyncio
from urllib.parse import urljoin

from docdocs.network import apply as apply_network
from docdocs.recorder import SceneContext, Take
from docdocs.serve import RefServer

PHONE = (390, 844)  # CSS pixels of the phone screen

WRAPPER = """<!doctype html><html><head><meta charset="utf-8"><style>
html, body { margin: 0; height: 100%; overflow: hidden; background:
  radial-gradient(ellipse at 85% 10%, rgb(0 200 255 / .10), transparent 55%),
  radial-gradient(ellipse at 10% 95%, rgb(245 158 11 / .07), transparent 50%), #080A0F; }
.phone { position: absolute; left: LEFTpx; top: TOPpx; width: OUTERWpx; height: OUTERHpx; border-radius: 34px;
  background: #11161f; border: 1px solid #2a3140; box-shadow: 0 30px 80px rgb(0 0 0 / .55), inset 0 0 0 6px #0b0f16; }
.screen { position: absolute; left: BEZELpx; top: BEZELpx; width: SCREENWpx; height: SCREENHpx; border-radius: 24px;
  overflow: hidden; background: #fff; }
iframe { width: 390px; height: 844px; border: 0; transform: scale(SCALE); transform-origin: 0 0; display: block; }
</style></head><body><div class="phone"><div class="screen"><iframe name="app" src="about:blank"></iframe></div></div></body></html>"""


def wrapper(view_w: int, view_h: int) -> str:
    top_margin, bottom_margin, bezel = 74, 26, 12
    scale = (view_h - top_margin - bottom_margin - 2 * bezel) / PHONE[1]
    screen_w, screen_h = PHONE[0] * scale, PHONE[1] * scale
    outer_w, outer_h = screen_w + 2 * bezel, screen_h + 2 * bezel
    left = view_w * 0.36 - outer_w / 2
    values = {"LEFT": left, "TOP": top_margin, "OUTERW": outer_w, "OUTERH": outer_h, "BEZEL": bezel,
              "SCREENW": screen_w, "SCREENH": screen_h, "SCALE": round(scale, 4)}
    html = WRAPPER
    for key in ("SCREENW", "SCREENH", "OUTERW", "OUTERH", "BEZEL", "LEFT", "TOP", "SCALE"):
        html = html.replace(key, f"{values[key]:.2f}" if key != "SCALE" else str(values[key]))
    return html


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    system = ctx.storyboard.systems[raw["system"]]
    repo = ctx.storyboard.resolve(system.get("repo", "."))
    base = system["baseUrl"]
    framed = raw.get("device") == "phone" and ctx.fmt.css_width > ctx.fmt.css_height

    # Serving runs blocking steps (install, build); keep them off the event loop.
    server = RefServer(system, repo, raw.get("checkout"), log=lambda m: print(m, flush=True))
    await asyncio.to_thread(server.__enter__)
    try:
        page = ctx.page
        await ctx.prepare(
            badge=raw.get("badge", "").upper(),
            badgeTone=raw.get("badgeColor", "after" if raw.get("checkout") == "after" else "before"),
            layoutShift="layout-shift" in raw.get("overlay", []),
            holdShifts=bool(raw.get("holdShifts")),
            bigCounter=framed,
            labelBackdrop=True,
        )
        if framed:
            # Serve the frame from the app's own origin, so the app runs in the same
            # process: the same throttling applies, and its shifts reach the HUD.
            frame_url = urljoin(base, "/__docdocs/phone")
            ctx.check(frame_url)
            body = wrapper(ctx.fmt.css_width, ctx.fmt.css_height)
            await page.route(frame_url, lambda route: route.fulfill(status=200, content_type="text/html", body=body))
            await page.goto(frame_url)
            app = page.frame(name="app")

            async def rect_of(selector: str):
                """The element's box in the frame's coordinates, trimmed to the phone's screen."""
                box = await app.locator(selector).first.bounding_box()
                screen = await page.locator(".screen").bounding_box()
                if not box or not screen:
                    return None
                left, top = max(box["x"], screen["x"]), max(box["y"], screen["y"])
                right = min(box["x"] + box["width"], screen["x"] + screen["width"])
                bottom = min(box["y"] + box["height"], screen["y"] + screen["height"])
                return {"left": left, "top": top, "width": max(0, right - left), "height": max(0, bottom - top)}

            ctx.resolve_rect = rect_of
        else:
            await ctx.show_html("<!doctype html><html style='background:#fff'><body></body></html>", "blank.html")
            app = page.main_frame
            if raw.get("start"):
                url = urljoin(base, raw["start"])
                ctx.check(url)
                await app.goto(url, wait_until="load")
                await page.evaluate("document.fonts.ready")
                await ctx.restore_hud()
        await apply_network(page, raw.get("network"))
        await ctx.begin()

        async def act(action: dict) -> None:
            (name, value), *_ = action.items()
            if name == "goto":
                url = urljoin(base, value)
                ctx.check(url)
                await app.goto(url, wait_until="commit")
                if not framed:
                    await ctx.restore_hud()
            elif name == "waitFor":
                await app.wait_for_selector(value, state="visible", timeout=float(action.get("timeout", 60000)))
            elif name == "scroll":
                if isinstance(value, (int, float)):
                    await app.evaluate("y => window.scrollBy({top: y, behavior: 'smooth'})", value)
                else:
                    await app.locator(value).first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'center'})")
                await asyncio.sleep(0.9)
            elif name == "click":
                if action.get("instant"):
                    await app.locator(value).first.dispatch_event("click")
                else:
                    await app.click(value)
            elif name == "type":
                field = app.locator(value).first
                await field.click()
                await field.press_sequentially(action["text"], delay=float(action.get("delay", 45)))
            elif name == "select":
                await app.locator(value).first.select_option(action["value"])
            elif name == "press":
                await page.keyboard.press(value)
            elif name == "reload":
                await app.evaluate("location.reload()")
                if not framed:
                    await ctx.restore_hud()
            elif name == "clearShifts":
                await ctx.hud("clearShifts")
            else:
                raise ValueError(f"{ctx.scene.label}: unknown browser action {name!r}")

        await ctx.play(act)
        return await ctx.end()
    finally:
        await asyncio.to_thread(server.__exit__, None, None, None)
