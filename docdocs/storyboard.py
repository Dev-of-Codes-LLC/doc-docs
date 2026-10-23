"""Load and check a storyboard.

A storyboard is one JSON file: the video's id and title, the systems it
films, the formats to render, and a list of scenes. Each scene is a list of
beats; a beat is one sentence of narration plus the actions it describes.
Paths in a storyboard are relative to the storyboard's folder.

Optional top-level settings:

- voiceSpeed  1.0 is Piper's pace; 1.08 is a little brisker
- captions    formats that get word-by-word captions, e.g. ["9:16"]
- series      a JSON file with "intro" and "outro" scene lists, added to
              the start and end of every episode that names it
- sfx         true adds a soft whoosh at each scene change
- music       {"file": "music/bed.mp3", "volume": 0.18}: a bed that dips
              under the voice. Use only music you have the rights to.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

SCENE_TYPES = ("card", "browser", "code", "terminal", "explain")

# Kokoro's weights are Apache-2.0, so its voices are safe for commercial videos.
# Check the licence of any other voice: some Piper voices are non-commercial only.
DEFAULT_VOICE = "kokoro:am_michael"


@dataclass(frozen=True)
class Format:
    name: str  # "16:9" or "9:16"
    css_width: int
    css_height: int
    scale: float

    @property
    def width(self) -> int:
        return round(self.css_width * self.scale)

    @property
    def height(self) -> int:
        return round(self.css_height * self.scale)

    @property
    def slug(self) -> str:
        return self.name.replace(":", "x")


FORMATS = {
    "16:9": Format("16:9", 1280, 720, 1.5),
    # A phone-width CSS viewport, so pages lay out as they do on a phone.
    "9:16": Format("9:16", 432, 768, 2.5),
}


@dataclass
class Beat:
    say: str | None
    actions: list[dict]
    hold_ms: int
    label: str | None = None  # a key phrase on screen; *word* is the accent
    speed: float = 1.0  # play this beat faster; the video says so on screen
    pause_ms: int = 0  # extra silence after the sentence, before the next beat


@dataclass
class Scene:
    index: int  # 1-based, as people count scenes
    type: str
    beats: list[Beat]
    raw: dict

    @property
    def label(self) -> str:
        return f"scene {self.index} ({self.type})"


@dataclass
class Storyboard:
    path: Path
    id: str
    title: str
    formats: list[Format]
    systems: dict[str, dict]
    scenes: list[Scene]
    measure: dict | None
    voice: str
    raw: dict = field(repr=False)
    voice_speed: float = 1.0
    captions: frozenset = frozenset()
    sfx: bool = False
    music: dict | None = None

    @property
    def base_dir(self) -> Path:
        return self.path.parent

    @property
    def build_dir(self) -> Path:
        return self.base_dir / "build"

    def resolve(self, relative: str) -> Path:
        return (self.base_dir / relative).resolve()


class StoryboardError(Exception):
    pass


def load(path: str | Path) -> Storyboard:
    path = Path(path).resolve()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise StoryboardError(f"{path}: no such file") from None
    except json.JSONDecodeError as e:
        raise StoryboardError(f"{path}: not valid JSON ({e})") from None

    problems: list[str] = []
    for key in ("id", "title", "scenes"):
        if key not in raw:
            problems.append(f"missing {key!r}")

    formats = []
    for name in raw.get("formats", ["16:9"]):
        if name in FORMATS:
            formats.append(FORMATS[name])
        else:
            problems.append(f"unknown format {name!r} (use {', '.join(FORMATS)})")

    systems = raw.get("systems", {})
    for name, system in systems.items():
        if "baseUrl" not in system:
            problems.append(f"system {name!r}: missing 'baseUrl'")

    scene_list = list(raw.get("scenes", []))
    if raw.get("series"):
        series_path = (path.parent / raw["series"]).resolve()
        try:
            text = series_path.read_text(encoding="utf-8")
            # {episode}, {title} and {next} in the series file come from this storyboard.
            for key in ("episode", "title", "next"):
                text = text.replace("{" + key + "}", json.dumps(str(raw.get(key, "")))[1:-1])
            series = json.loads(text)
        except (OSError, json.JSONDecodeError) as e:
            raise StoryboardError(f"{path}: cannot read series file {series_path}: {e}") from None
        intro, outro = list(series.get("intro", [])), list(series.get("outro", []))
        # The hook comes first when the series says so: hook, then the intro sting.
        cut = 1 if series.get("introAfterFirst") and scene_list else 0
        scene_list = scene_list[:cut] + intro + scene_list[cut:] + outro

    scenes = []
    for i, s in enumerate(scene_list, start=1):
        kind = s.get("type")
        if kind not in SCENE_TYPES:
            problems.append(f"scene {i}: type must be one of {', '.join(SCENE_TYPES)}")
            continue
        if kind == "browser" and s.get("system") not in systems:
            problems.append(f"scene {i}: system {s.get('system')!r} is not in 'systems'")
        beats = []
        for b in s.get("beats", []):
            actions = b.get("do", [])
            if not isinstance(actions, list):
                problems.append(f"scene {i}: a beat's 'do' must be a list")
                actions = []
            speed = float(b.get("speed", 1))
            if not 0.5 <= speed <= 8:
                problems.append(f"scene {i}: a beat's speed must be between 0.5 and 8")
            beats.append(Beat(say=b.get("say"), actions=actions, hold_ms=int(b.get("hold", 0)),
                              label=b.get("label"), speed=speed, pause_ms=int(b.get("pause", 0))))
        if not beats:
            # A scene with no beats still shows for a moment.
            beats.append(Beat(say=None, actions=[], hold_ms=int(s.get("hold", 2500))))
        scenes.append(Scene(index=i, type=kind, beats=beats, raw=s))

    if problems:
        raise StoryboardError(f"{path}:\n  - " + "\n  - ".join(problems))

    return Storyboard(
        path=path,
        id=raw["id"],
        title=raw["title"],
        formats=formats,
        systems=systems,
        scenes=scenes,
        measure=raw.get("measure"),
        voice=raw.get("voice", DEFAULT_VOICE),
        raw=raw,
        voice_speed=float(raw.get("voiceSpeed", 1.0)),
        captions=frozenset(raw.get("captions", [])),
        sfx=bool(raw.get("sfx", False)),
        music=raw.get("music"),
    )
