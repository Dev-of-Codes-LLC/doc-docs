"""Network and CPU profiles, shared by browser scenes and `docdocs measure`.

slow-4g matches Lighthouse's mobile Slow 4G profile, so what a video shows
and what `measure` reports are the same conditions.
"""

PROFILES = {
    "none": None,
    "slow-4g": {"latency_ms": 562.5, "down_kbps": 1474.56, "up_kbps": 675, "cpu": 4, "label": "Slow 4G"},
    "fast-3g": {"latency_ms": 562.5, "down_kbps": 1474.56 * 0.9, "up_kbps": 675, "cpu": 4, "label": "Fast 3G"},
}


def profile(name: str | None) -> dict | None:
    if name in (None, "none"):
        return None
    if name not in PROFILES:
        raise ValueError(f"unknown network profile {name!r} (use {', '.join(PROFILES)})")
    return PROFILES[name]


async def apply(page, name: str | None) -> None:
    """Throttle one page over the Chrome DevTools Protocol."""
    p = profile(name)
    if p is None:
        return
    cdp = await page.context.new_cdp_session(page)
    await cdp.send("Network.enable")
    await cdp.send(
        "Network.emulateNetworkConditions",
        {
            "offline": False,
            "latency": p["latency_ms"],
            "downloadThroughput": p["down_kbps"] * 1024 / 8,
            "uploadThroughput": p["up_kbps"] * 1024 / 8,
        },
    )
    await cdp.send("Emulation.setCPUThrottlingRate", {"rate": p["cpu"]})
