"""Browser scenes: the real product, in the real browser.

    {"type": "browser", "system": "demo", "checkout": "before", "network": "slow-4g",
     "overlay": ["layout-shift"], "badge": "before · Slow 4G",
     "beats": [{"say": "...", "label": "the page *jumps*", "do": [{"goto": "/products"}, {"waitFor": "main[data-state=loaded]"}]}]}

checkout   a git ref to build and serve first (optional; else the working tree)
network    a profile from docdocs.network (optional)
overlay    "layout-shift" outlines every element that moves, with a running CLS
badge      a label in the corner; badgeColor "before" (amber) or "after" (cyan)

Actions: goto, waitFor, scroll, click, reload, and the common wait, zoom,
unzoom and label. Labels get a navy backdrop here, so they read on any page.
"""

import asyncio
from urllib.parse import urljoin

from docdocs.network import apply as apply_network
from docdocs.recorder import SceneContext, Take
from docdocs.serve import RefServer


async def record(ctx: SceneContext) -> Take:
    raw = ctx.scene.raw
    system = ctx.storyboard.systems[raw["system"]]
    repo = ctx.storyboard.resolve(system.get("repo", "."))
    base = system["baseUrl"]

    # Serving runs blocking steps (install, build); keep them off the event loop.
    server = RefServer(system, repo, raw.get("checkout"), log=lambda m: print(m, flush=True))
    await asyncio.to_thread(server.__enter__)
    try:
        page = ctx.page
        await ctx.prepare(
            badge=raw.get("badge", "").upper(),
            badgeTone=raw.get("badgeColor", "after" if raw.get("checkout") == "after" else "before"),
            layoutShift="layout-shift" in raw.get("overlay", []),
            labelBackdrop=True,
        )
        await ctx.show_html("<!doctype html><html style='background:#fff'><body></body></html>", "blank.html")
        await apply_network(page, raw.get("network"))
        await ctx.begin()

        async def act(action: dict) -> None:
            (name, value), *_ = action.items()
            if name == "goto":
                url = urljoin(base, value)
                ctx.check(url)
                await page.goto(url, wait_until="commit")
                await ctx.restore_hud()
            elif name == "waitFor":
                await page.wait_for_selector(value, state="visible", timeout=float(action.get("timeout", 60000)))
            elif name == "scroll":
                if isinstance(value, (int, float)):
                    await page.evaluate("y => window.scrollBy({top: y, behavior: 'smooth'})", value)
                else:
                    await page.locator(value).first.evaluate("el => el.scrollIntoView({behavior: 'smooth', block: 'center'})")
                await asyncio.sleep(0.9)
            elif name == "click":
                await page.click(value)
            elif name == "reload":
                await page.reload(wait_until="commit")
                await ctx.restore_hud()
            else:
                raise ValueError(f"{ctx.scene.label}: unknown browser action {name!r}")

        await ctx.play(act)
        return await ctx.end()
    finally:
        await asyncio.to_thread(server.__exit__, None, None, None)
