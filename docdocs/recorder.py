"""Record scenes as lossless frames.

Every scene is a web page played in headless Chromium. Frames come from the
Chrome DevTools Protocol screencast as PNG, each with the time it was drawn,
so nothing is encoded until the final stitch. A scene's take (its frames,
length, narrated beats and sped-up stretches) is saved next to its frames,
so one scene can be re-recorded without the others.

Every page also gets the HUD (hud.js): key-phrase labels, captions, badges,
zooms and the fade through navy between scenes are drawn in the page while
it is recorded, timed by the same clock as the narration.
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

from docdocs.captions import timings
from docdocs.hosts import check_url
from docdocs.paths import package_dir
from docdocs.storyboard import Format, Scene, Storyboard
from docdocs.voice import Clip, Voice

BEAT_GAP_S = 0.15  # silence after each sentence: the reference pace is 0.1-0.4 s
LEAD_IN_S = 0.1  # time on screen before the first beat of a scene
ANCHOR_LEAD_MS = 120  # an action anchored to a word fires this much before it, so the eye meets the ear


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
    segments: list[tuple[float, float, float]] = field(default_factory=list)  # (start, end, speed) in scene seconds

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(asdict(self), indent=1), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Take":
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            duration=raw["duration"],
            frames=[tuple(f) for f in raw["frames"]],
            marks=[Mark(**m) for m in raw["marks"]],
            segments=[tuple(s) for s in raw.get("segments", [])],
        )


class Brand:
    def __init__(self, name: str = "devofcodes", path: Path | None = None):
        self.dir = (path or package_dir() / "brands" / name).resolve()
        if not (self.dir / "brand.css").exists():
            raise FileNotFoundError(f"brand folder {self.dir} has no brand.css")
        self.meta = json.loads((self.dir / "brand.json").read_text(encoding="utf-8"))
        self._font_css = None

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

    def font_css(self) -> str:
        """The HUD's fonts as data URIs, so they load on any page, including the product's own."""
        if self._font_css is None:
            faces = [("DD Literata", "literata-400", 400), ("DD Literata", "literata-600", 600),
                     ("DD Syne", "syne-800", 800), ("DD Mono", "jetbrains-mono-700", 700)]
            rules = []
            for family, file, weight in faces:
                data = base64.b64encode((self.dir / "fonts" / f"{file}.woff2").read_bytes()).decode()
                rules.append(f"@font-face {{ font-family: '{family}'; font-weight: {weight}; "
                             f"src: url(data:font/woff2;base64,{data}) format('woff2'); }}")
            self._font_css = "\n".join(rules)
        return self._font_css


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
        self._stopping = False

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
        if self._stopping:
            return  # a frame drawn while stopping; the take already ends
        name = f"{len(self.frames):06d}.png"
        (self.dir / name).write_bytes(base64.b64decode(params["data"]))
        at = params["metadata"].get("timestamp", time.time()) - self.t0
        self.frames.append((max(0.0, at), name))
        task = asyncio.ensure_future(self._ack(params["sessionId"]))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _ack(self, session_id: int) -> None:
        try:
            await self._cdp.send("Page.screencastFrameAck", {"sessionId": session_id})
        except Exception:  # noqa: BLE001 - the page may close while a frame is in flight
            pass

    def now(self) -> float:
        return time.time() - self.t0

    async def stop(self) -> float:
        duration = self.now()
        self._stopping = True
        await self._cdp.send("Page.stopScreencast")
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
        await self._cdp.detach()
        if not self.frames:
            raise RuntimeError(f"no frames captured in {self.dir}")
        return duration


class SceneContext:
    """What a scene recorder gets: the page, the clips, the HUD and the beat player."""

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
        self.segments: list[tuple[float, float, float]] = []
        self.file_roots = [storyboard.build_dir, brand.dir, package_dir()]
        # Cards already show their words, so they get no captions unless they ask.
        self.captions = fmt.name in storyboard.captions and scene.raw.get("captions", scene.type != "card")
        self.hud_state: dict = {}
        self.resolve_rect = None  # set by scenes whose content lives in a frame

    # -- setup ---------------------------------------------------------------

    async def prepare(self, **config) -> None:
        """Inject the HUD into every page this scene opens. Call before the first navigation."""
        cfg = {"fontCss": self.brand.font_css(), "captionStyle": self.storyboard.caption_style, **config}
        script = f"window.__docdocs = {json.dumps(cfg)};\n" + (package_dir() / "hud.js").read_text(encoding="utf-8")
        await self.page.add_init_script(script)

    def check(self, url: str) -> None:
        last = None
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

    # -- HUD -----------------------------------------------------------------

    async def hud(self, method: str, *args) -> None:
        await self.page.evaluate(
            "([m, args]) => window.__docdocsHud && window.__docdocsHud[m](...args)", [method, list(args)]
        )

    async def restore_hud(self) -> None:
        """Re-apply labels, captions and badges after a navigation replaced the page."""
        try:
            await self.page.wait_for_function("() => !!window.__docdocsHud", timeout=10000)
            await self.page.evaluate("s => window.__docdocsHud.restore(s)", self.hud_state)
        except Exception:  # noqa: BLE001 - a page that never loads keeps going without its HUD
            pass

    # -- the scene's life ----------------------------------------------------

    async def begin(self) -> None:
        """Start recording behind the navy cover, then fade it out. With "fadeIn": false the first frame is the scene."""
        fade = self.scene.raw.get("fadeIn", True)
        if fade:
            await self.hud("cover", True, 0)
            # Let the cover reach the screen first, or the take opens on a frame without it.
            await self.page.evaluate("() => new Promise(r => requestAnimationFrame(() => requestAnimationFrame(r)))")
        await self.capture.start()
        await asyncio.sleep(0.05)
        if fade:
            await self.hud("cover", False, self.storyboard.fade_ms)
        await asyncio.sleep(LEAD_IN_S)

    async def end(self) -> Take:
        """Fade to navy, stop recording, and return the take. With "fadeOut": false the scene holds to the end."""
        await self.hud("label", None)
        if self.scene.raw.get("fadeOut", True):
            await self.hud("cover", True, self.storyboard.fade_ms)
            await asyncio.sleep(self.storyboard.fade_ms / 1000 + 0.05)
        duration = await self.capture.stop()
        return Take(duration=duration, frames=self.capture.frames, marks=self.marks, segments=self.segments)

    async def common(self, action: dict) -> bool:
        """Actions every scene type understands. Return False if this one is not common.

        wait, zoom, unzoom and label, plus sheets laid over the scene: "sheet" adds or
        updates one (see hud.js), and "sheets" bundles them ("bundle"), sends the bundle
        off ("ship") or fades them ("clear").
        """
        (name, value), *_ = action.items()
        if name == "wait":
            await asyncio.sleep(float(value) / 1000)
        elif name == "zoom":
            scale = action.get("scale", 1.8)
            if isinstance(scale, dict):  # per format: {"16:9": 1.35, "9:16": 1.15}; a format left out gets no zoom
                if self.fmt.name not in scale:
                    return True
                scale = scale[self.fmt.name]
            target = value
            if isinstance(value, str) and self.resolve_rect:
                target = await self.resolve_rect(value) or value
            spec = {"target": target, "scale": float(scale), "ms": int(action.get("ms", 700))}
            self.hud_state["zoom"] = spec
            await self.hud("zoom", spec)
            await asyncio.sleep(spec["ms"] / 1000)
        elif name == "unzoom":
            if not self.hud_state.get("zoom"):
                return True
            self.hud_state["zoom"] = None
            await self.hud("zoom", None)
            await asyncio.sleep(0.7)
        elif name == "label":
            self.hud_state["label"] = value
            await self.hud("label", value)
        elif name == "sheet":
            sheets = self.hud_state.setdefault("sheets", {})
            sheets[value["id"]] = {**sheets.get(value["id"], {}), **value}
            await self.hud("sheet", value)
        elif name == "sheets":
            if value not in ("bundle", "ship", "clear"):
                raise ValueError(f"{self.scene.label}: sheets takes bundle, ship or clear, got {value!r}")
            self.hud_state["sheetsOp"] = value
            await self.hud("sheets", value)
        else:
            return False
        return True

    async def play(self, run_action) -> None:
        """Run every beat: say the sentence while its actions run, then wait for the longer of the two.

        An action with "at" waits for its moment: "at": "picture" fires just
        before the voice reaches that word (ANCHOR_LEAD_MS; the first match
        after the previous anchor), "at": 1200 fires 1.2 s into the beat.
        Actions without "at" run straight away, in order.

        A beat with speed > 1 runs in real time but is played back faster, so
        it waits until its sentence fits the sped-up playback.
        """
        for beat in self.scene.beats:
            start = self.capture.now()
            began = time.time()
            clip = self.clips.get(beat.say) if beat.say else None
            shown = beat.text or (clip.text if clip else "")
            chunks = timings(shown, clip.path, stretch=beat.speed) if clip else []
            words = [(w, t) for c in chunks for w, t in zip(c["words"], c["times"])]
            if beat.label is not None:
                self.hud_state["label"] = beat.label
                await self.hud("label", beat.label)
            if beat.speed != 1:
                self.hud_state["speed"] = beat.speed
                await self.hud("speed", beat.speed)
            captioned = self.captions if beat.captions is None else beat.captions and self.fmt.name in self.storyboard.captions
            if clip and captioned:
                spec = {"chunks": chunks, "t0": round(began * 1000)}
                self.hud_state["caption"] = spec
                await self.hud("caption", spec)
            elif self.hud_state.get("caption"):
                self.hud_state["caption"] = None
                await self.hud("caption", None)
            cursor = 0
            for action in beat.actions:
                if "at" in action:
                    action = dict(action)
                    at = action.pop("at")
                    if isinstance(at, (int, float)):
                        target_ms = at * beat.speed
                    else:
                        found = next((k for k in range(cursor, len(words))
                                      if _bare(words[k][0]) == _bare(str(at))), None)
                        if found is None:
                            raise ValueError(f"{self.scene.label}: 'at': {at!r} is not a word of {beat.say!r}")
                        cursor = found + 1
                        target_ms = max(0, words[found][1][0] - ANCHOR_LEAD_MS * beat.speed)
                    wait = target_ms / 1000 - (time.time() - began)
                    if wait > 0:
                        await asyncio.sleep(wait)
                if not await self.common(action):
                    await run_action(action)
            # Time the beat from the end of the speech, not the end of the clip's trailing silence.
            spoken = clip.speech_end if clip else 0.0
            need = (spoken + BEAT_GAP_S + beat.pause_ms / 1000) * beat.speed if clip else 0.0
            need = max(need, beat.hold_ms / 1000 * beat.speed if beat.hold_ms else (0.0 if clip else 1.0))
            remaining = need - (time.time() - began)
            if remaining > 0:
                await asyncio.sleep(remaining)
            if beat.speed != 1:
                self.segments.append((start, self.capture.now(), beat.speed))
                self.hud_state["speed"] = None
                await self.hud("speed", None)
            if clip:
                self.marks.append(Mark(start=start, text=shown, clip=str(clip.path), seconds=clip.seconds))
        self.hud_state["caption"] = None
        await self.hud("caption", None)


def _bare(word: str) -> str:
    return "".join(ch for ch in word.lower() if ch.isalnum())


def scene_dir(storyboard: Storyboard, fmt: Format, scene: Scene) -> Path:
    return storyboard.build_dir / fmt.slug / f"scene-{scene.index:02d}"


async def record(storyboard: Storyboard, only: set[int] | None = None, formats: list[Format] | None = None,
                 voice: Voice | None = None, log=print, gpu: bool | None = None) -> None:
    """Record every scene (or only some) in every format, saving one take per scene.

    `gpu` puts the browser on the machine's own GPU (docdocs/gpu.py); left
    as None, the storyboard's own "gpu" setting decides.
    """
    from playwright.async_api import async_playwright

    from docdocs.gpu import launch_args, renderer_of, report

    from docdocs.scenes import RECORDERS

    voice = voice or Voice(storyboard.voice, speed=storyboard.voice_speed)
    says = [beat.say for scene in storyboard.scenes for beat in scene.beats if beat.say]
    voice.prepare(says)
    clips = {say: voice.clip(say) for say in dict.fromkeys(says)}
    log(f"voice: {len(clips)} sentences ready ({voice.spec}, speed {voice.speed})")

    measurements = None
    mpath = storyboard.base_dir / "measurements.json"
    if mpath.exists():
        measurements = json.loads(mpath.read_text(encoding="utf-8"))

    brand = Brand(storyboard.raw.get("brand", "devofcodes"))
    async with async_playwright() as pw:
        on_gpu = storyboard.gpu if gpu is None else gpu
        browser = await pw.chromium.launch(args=launch_args(on_gpu))
        try:
            if on_gpu:
                # Say what it got: where the flags do not take, the recording is in software after all.
                log(report(await renderer_of(browser)))
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
