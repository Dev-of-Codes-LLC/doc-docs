"""Narration: one cached clip per sentence.

Voices are named "<provider>:<voice>":

- kokoro:<voice>  Kokoro, local and free, and far more natural than Piper.
  Weights are Apache-2.0. Get the model with `docdocs voices install kokoro`,
  and the runtime with `pip install kokoro-onnx`. Its phonemizer and
  espeak-ng are GPL-3.0, so DOC Docs runs it in a separate process
  (kokoro_worker.py) and never imports it. Voices: am_michael, am_fenrir,
  am_puck, am_echo, bm_george, af_heart and more.
- piper:<voice>   Piper, local and free, more robotic. GPL-3.0, also run as
  a separate program. Get a voice with `docdocs voices install <voice>`.
- silent          No audio. Each clip is as long as the sentence would take
  to say, so timing and captions can be checked without a voice.

Check the licence of any voice before you publish: some Piper voices are
non-commercial only. Clips are cached by provider, voice, speed and text,
so changing one sentence re-synthesizes one clip.
"""

import hashlib
import json
import subprocess
import sys
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path

from docdocs.paths import user_dir

SAMPLE_RATE = 22050  # the silent voice's rate; real clips keep their own and the stitch resamples

KOKORO_FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}


@dataclass(frozen=True)
class Clip:
    text: str
    path: Path
    seconds: float
    speech_end: float  # where the speech stops; the rest is trailing silence


class VoiceError(Exception):
    pass


def voices_dir() -> Path:
    return user_dir() / "voices"


class Voice:
    def __init__(self, spec: str, speed: float = 1.0):
        provider, _, name = spec.partition(":")
        if provider not in ("kokoro", "piper", "silent"):
            raise VoiceError(f"unknown voice {spec!r}: use kokoro:<voice>, piper:<voice> or silent")
        self.spec = spec
        self.speed = speed
        self.provider = provider
        self.name = name
        self.cache = user_dir() / "cache" / "voice" / (spec.replace(":", "-") or "silent")

    def _path(self, text: str) -> Path:
        key = hashlib.sha256(f"{self.spec}\n{self.speed}\n{text}".encode()).hexdigest()[:20]
        return self.cache / f"{key}.wav"

    def prepare(self, texts: list[str]) -> None:
        """Synthesize every missing clip. Kokoro does them in one run, so its model loads once."""
        missing = [t for t in dict.fromkeys(texts) if not self._path(t).exists()]
        if not missing:
            return
        self.cache.mkdir(parents=True, exist_ok=True)
        if self.provider == "kokoro":
            self._synthesize_kokoro(missing)
            return
        for text in missing:
            tmp = self._path(text).with_suffix(".tmp")
            if self.provider == "piper":
                self._synthesize_piper(text, tmp)
            else:
                _write_silence(tmp, _estimate_seconds(text) / self.speed)
            tmp.replace(self._path(text))

    def clip(self, text: str) -> Clip:
        path = self._path(text)
        if not path.exists():
            self.prepare([text])
        from docdocs.captions import speech_bounds

        return Clip(text=text, path=path, seconds=wav_seconds(path), speech_end=speech_bounds(path)[1])

    def _synthesize_kokoro(self, texts: list[str]) -> None:
        folder = voices_dir() / "kokoro"
        model, voices = folder / "kokoro-v1.0.onnx", folder / "voices-v1.0.bin"
        if not model.exists() or not voices.exists():
            raise VoiceError("the Kokoro model is not installed. Run: docdocs voices install kokoro")
        items = [{"text": " ".join(t.split()), "out": str(self._path(t).with_suffix(".tmp"))} for t in texts]
        job = {"model": str(model), "voices": str(voices), "voice": self.name or "am_michael",
               "speed": self.speed, "lang": "en-gb" if self.name.startswith("b") else "en-us", "items": items}
        result = subprocess.run([sys.executable, "-m", "docdocs.kokoro_worker"], input=json.dumps(job),
                                capture_output=True, text=True, encoding="utf-8")
        if result.returncode != 0:
            raise VoiceError(f"kokoro failed: {result.stderr[-800:]}")
        for t, item in zip(texts, items):
            Path(item["out"]).replace(self._path(t))

    def _synthesize_piper(self, text: str, out: Path) -> None:
        model = voices_dir() / f"{self.name}.onnx"
        if not model.exists():
            raise VoiceError(f"voice {self.name!r} is not installed. Run: docdocs voices install {self.name}")
        result = subprocess.run(
            [sys.executable, "-m", "piper", "-m", str(model), "-f", str(out), "--length-scale", f"{1 / self.speed:.3f}"],
            input=" ".join(text.split()), capture_output=True, text=True, encoding="utf-8",
        )
        if result.returncode != 0 or not out.exists():
            raise VoiceError(f"piper failed for {text[:40]!r}: {result.stderr[-800:]}")


def install(name: str) -> Path:
    """Download the Kokoro model ("kokoro") or a Piper voice into the voices folder."""
    if name == "kokoro":
        folder = voices_dir() / "kokoro"
        folder.mkdir(parents=True, exist_ok=True)
        for file, url in KOKORO_FILES.items():
            target = folder / file
            if not target.exists():
                print(f"downloading {file} ...", flush=True)
                tmp = target.with_suffix(".part")
                urllib.request.urlretrieve(url, tmp)
                tmp.replace(target)
        return folder
    voices_dir().mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "piper.download_voices", name, "--download-dir", str(voices_dir())], check=True)
    return voices_dir() / f"{name}.onnx"


def wav_seconds(path: Path) -> float:
    with wave.open(str(path)) as wf:
        return wf.getnframes() / wf.getframerate()


def _estimate_seconds(text: str) -> float:
    return max(1.2, len(text.split()) / 2.6)


def _write_silence(path: Path, seconds: float) -> None:
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b"\x00\x00" * round(seconds * SAMPLE_RATE))
