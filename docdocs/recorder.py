"""Record scenes as lossless frames.

Every scene is a web page played in headless Chromium. Frames come from the
Chrome DevTools Protocol screencast as PNG, each with the time it was drawn,
so nothing is encoded until the final stitch. A scene's take (its frames,
length and narrated beats) is saved next to its frames, so one scene can be
re-recorded without the others.
"""

import asyncio
import base64
import html
import json
import shutil
import string
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from docdocs.hosts import check_url
from docdocs.paths import package_dir
from docdocs.storyboard import Format, Scene, Storyboard
from docdocs.voice import Clip, Voice

BEAT_GAP_S = 0.35  # silence after each sentence
LEAD_IN_S = 0.4  # time on screen before the first beat of a scene


@dataclass
class Mark:
    """One narrated beat: when it starts in the scene, and its clip."""

    start: float
    text: str
    clip: str
    seconds: float


@dataclass
class Take:
    duration: float
    frames: list[tuple[float, str]] = field(default_factory=list)  # (seconds from scene start, file)
    marks: list[Mark] = field(default_factory=list)

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Take":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            duration=raw["duration"],
            frames=[tuple(f) for f in raw["frames"]],
            marks=[Mark(**m) for m in raw["marks"]],
        )


class Brand:
    def __init__(self, name: str = "devofcodes", path: Path | None = None):
        self.dir = (path or package_dir() / "brands" / name).resolve()
        if not (self.dir / "brand.css").exists():
            raise FileNotFoundError(f"brand folder {self.dir} has no brand.css")
        self.meta = json.loads((self.dir / "brand.json").read_text(encoding="utf-8"))

    def template(self, name: str) -> string.Template:
        path = self.dir / "templates" / f"{name}.html"
        if not path.exists():
            raise FileNotFoundError(f"brand template {name!r} not found in {path.parent}")
        return string.Template(path.read_text(encoding="utf-8"))

    def page(self, body: str, title: str = "", head: str = "") -> str:
        """A full page with the brand stylesheet; relative URLs resolve in the brand folder."""
        return (
            "<!doctype html><html><head><meta charset='utf-8'>"
            f"<base href='{self.dir.as_uri()}/'>"
            "<link rel='stylesheet' href='brand.css'>"
            f"<title>{html.escape(title)}</title>{head}</head><body>{body}</body></html>"
        )


def fill(template: string.Template, fields: dict) -> str:
    """Substitute fields, escaping text. Keys ending in _html are inserted as is."""
    values = {}
    for key, value in fields.items():
        values[key] = value if key.endswith("_html") else html.escape(str(value))
    for key in [k for k in values if k.endswith("_html")]:
        values[key[: -len("_html")]] = values[key]
    return template.safe_substitute(values)


class Capture:
    """Collect screencast frames from one page into a folder."""

    def __init__(self, page, fmt: Format, frames_dir: Path):
        self.page = page
        self.fmt = fmt
        self.dir = frames_dir
        self.frames: list[tuple[float, str]] = []
        self.t0 = 0.0
        self._cdp = None
        self._pending: set[asyncio.Task] = set()

    async def start(self) -> None:
        if self.dir.exists():
            shutil.rmtree(self.dir)
        self.dir.mkdir(parents=True)
        self._cdp = await self.page.context.new_cdp_session(self.page)
        self._cdp.on("Page.screencastFrame", self._on_frame)
        self.t0 = time.time()
        await self._cdp.send(
            "Page.startScreencast",
            {"format": "png", "maxWidth": self.fmt.width, "maxHeight": self.fmt.height, "everyNthFrame": 1},
        )

    def _on_frame(self, params: dict) -> None:
        name = f"{len(self.frames):06d}.png"
        (self.dir / name).write_bytes(base64.b64decode(params["data"]))
        at = params["metadata"].get("timestamp", time.time()) - self.t0
        self.frames.append((max(0.0, at), name))
        task = asyncio.ensure_future(self._cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    def now(self) -> float:
        return time.time() - self.t0

    async def stop(self) -> float:
        duration = self.now()
        await self._cdp.send("Page.stopScreencast")
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        await self._cdp.detach()
        if not self.frames:
            raise RuntimeError(f"no frames captured in {self.dir}")
        return duration


class SceneContext:
    """What a scene recorder gets: the page, the clips, and the beat player."""

    def __init__(self, storyboard: Storyboard, scene: Scene, fmt: Format, page, scene_dir: Path,
                 brand: Brand, clips: dict[str, Clip], measurements: dict | None):
        self.storyboard = storyboard
        self.scene = scene
        self.fmt = fmt
        self.page = page
        self.dir = scene_dir
        self.brand = brand
        self.clips = clips
        self.measurements = measurements
        self.capture = Capture(page, fmt, scene_dir / "frames")
        self.marks: list[Mark] = []
        self.file_roots = [storyboard.build_dir, brand.dir, package_dir()]

    def check(self, url: str) -> None:
        for root in self.file_roots:
            try:
                check_url(url, root)
                return
            except Exception as e:  # noqa: BLE001 - try the next root
                last = e
        raise last

    async def show_html(self, html_text: str, name: str = "page.html") -> None:
        """Write a page into the scene folder and open it."""
        path = self.dir / name
        path.write_text(html_text, encoding="utf-8")
        url = path.as_uri()
        self.check(url)
        await self.page.goto(url)
        await self.page.evaluate("document.fonts.ready")

    async def play(self, run_action) -> None:
        """Run every beat: say the sentence while its actions run, then wait for the longer of the two."""
        await asyncio.sleep(LEAD_IN_S)
        for beat in self.scene.beats:
            start = self.capture.now()
            began = time.time()
            clip = self.clips.get(beat.say) if beat.say else None
            for action in beat.actions:
                await run_action(action)
            need = clip.seconds + BEAT_GAP_S if clip else 0.0
            need = max(need, beat.hold_ms / 1000 if beat.hold_ms else (0.0 if clip else 1.0))
            remaining = need - (time.time() - began)
            if remaining > 0:
                await asyncio.sleep(remaining)
            if clip:
                self.marks.append(Mark(start=start, text=clip.text, clip=str(clip.path), seconds=clip.seconds))

    def take(self, duration: float) -> Take:
        return Take(duration=duration, frames=self.capture.frames, marks=self.marks)


def scene_dir(storyboard: Storyboard, fmt: Format, scene: Scene) -> Path:
    return storyboard.build_dir / fmt.slug / f"scene-{scene.index:02d}"


async def record(storyboard: Storyboard, only: set[int] | None = None, formats: list[Format] | None = None,
                 voice: Voice | None = None, log=print) -> None:
    """Record every scene (or only some) in every format, saving one take per scene."""
    from playwright.async_api import async_playwright

    from docdocs.scenes import RECORDERS

    voice = voice or Voice(storyboard.voice)
    clips = {}
    for scene in storyboard.scenes:
        for beat in scene.beats:
            if beat.say and beat.say not in clips:
                clips[beat.say] = voice.clip(beat.say)
    log(f"voice: {len(clips)} sentences ready ({voice.spec})")

    measurements = None
    mpath = storyboard.base_dir / "measurements.json"
    if mpath.exists():
        measurements = json.loads(mpath.read_text(encoding="utf-8"))

    brand = Brand(storyboard.raw.get("brand", "devofcodes"))
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        try:
            for fmt in formats or storyboard.formats:
                for scene in storyboard.scenes:
                    if only and scene.index not in only:
                        continue
                    sdir = scene_dir(storyboard, fmt, scene)
                    sdir.mkdir(parents=True, exist_ok=True)
                    log(f"[{fmt.name}] recording {scene.label}")
                    context = await browser.new_context(
                        viewport={"width": fmt.css_width, "height": fmt.css_height},
                        device_scale_factor=fmt.scale,
                    )
                    page = await context.new_page()
                    ctx = SceneContext(storyboard, scene, fmt, page, sdir, brand, clips, measurements)
                    try:
                        take = await RECORDERS[scene.type](ctx)
                    finally:
                        await context.close()
                    take.save(sdir / "take.json")
                    log(f"[{fmt.name}] {scene.label}: {take.duration:.1f} s, {len(take.frames)} frames")
        finally:
            await browser.close()
