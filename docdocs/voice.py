"""Narration: one cached clip per sentence.

Voices are named "<provider>:<voice>":

- piper:<voice>  Piper, local and free, on Windows, Linux and macOS. The
  voice model lives in <user dir>/voices; get it with
  `docdocs voices install <voice>`. Piper is GPL-3.0, so DOC Docs runs it
  as a separate program and never imports it.
- silent         No audio. Each clip is as long as the sentence would take
  to say, so timing and captions can be checked without a voice.

Clips are cached by provider, voice and text, so changing one sentence
re-synthesizes one clip.
"""

import hashlib
import subprocess
import sys
import wave
from dataclasses import dataclass
from pathlib import Path

from docdocs.paths import user_dir

SAMPLE_RATE = 22050  # Piper's rate; every clip and the episode track use it.


@dataclass(frozen=True)
class Clip:
    text: str
    path: Path
    seconds: float


class VoiceError(Exception):
    pass


def voices_dir() -> Path:
    return user_dir() / "voices"


class Voice:
    def __init__(self, spec: str, speed: float = 1.0):
        provider, _, name = spec.partition(":")
        if provider not in ("piper", "silent"):
            raise VoiceError(f"unknown voice {spec!r}: use piper:<voice> or silent")
        self.spec = spec
        self.speed = speed
        self.provider = provider
        self.name = name
        self.cache = user_dir() / "cache" / "voice" / (spec.replace(":", "-") or "silent")

    def clip(self, text: str) -> Clip:
        key = hashlib.sha256(f"{self.spec}\n{self.speed}\n{text}".encode()).hexdigest()[:20]
        path = self.cache / f"{key}.wav"
        if not path.exists():
            self.cache.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            if self.provider == "piper":
                self._synthesize_piper(text, tmp)
            else:
                _write_silence(tmp, _estimate_seconds(text) / self.speed)
            tmp.replace(path)
        return Clip(text=text, path=path, seconds=wav_seconds(path))

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
        with wave.open(str(out)) as wf:
            if wf.getframerate() != SAMPLE_RATE or wf.getnchannels() != 1:
                raise VoiceError(f"{self.name}: expected {SAMPLE_RATE} Hz mono, got {wf.getframerate()} Hz, {wf.getnchannels()} channels")


def install(name: str) -> Path:
    """Download a Piper voice into the voices folder."""
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
