"""Stitch the takes into one MP4 and one SRT per format.

Frames are lossless PNGs with the time each was drawn. For every 1/30 s of
the video, the stitch picks the frame that was on screen at that moment and
pipes it to ffmpeg, which encodes once to H.264 at exactly 30 fps. Scene
offsets come from the same frame count, and the narration is one WAV with
every clip placed where its beat started, so picture and voice cannot drift.
"""

import array
import math
import random
import shutil
import subprocess
import wave
from pathlib import Path

from docdocs.recorder import Take, scene_dir
from docdocs.storyboard import Format, Storyboard
from docdocs.voice import SAMPLE_RATE

FPS = 30


def ffmpeg_exe() -> str:
    found = shutil.which("ffmpeg")
    if found:
        return found
    import imageio_ffmpeg

    return imageio_ffmpeg.get_ffmpeg_exe()


def _srt_time(seconds: float) -> str:
    ms = round(seconds * 1000)
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def _rate(take: Take, at: float) -> float:
    """Playback speed at a moment of the take (1 outside sped-up stretches)."""
    for start, end, speed in take.segments:
        if start <= at < end:
            return speed
    return 1.0


def _out_time(take: Take, at: float) -> float:
    """Where a moment of the take lands in the video, after speed-ups."""
    out = at
    for start, end, speed in take.segments:
        overlap = max(0.0, min(at, end) - start)
        out -= overlap * (1 - 1 / speed)
    return out


def _whoosh(seconds: float = 0.55) -> array.array:
    """A soft, synthesized whoosh: filtered noise that swells and fades. No samples, no licence."""
    rng = random.Random(7)
    n = round(seconds * SAMPLE_RATE)
    out = array.array("h", bytes(2 * n))
    low = 0.0
    for i in range(n):
        k = i / n
        envelope = math.sin(math.pi * k) ** 2 * (1 - 0.4 * k)
        cutoff = 0.02 + 0.18 * math.sin(math.pi * k)  # opens, then closes
        low += cutoff * (rng.uniform(-1, 1) - low)
        out[i] = int(max(-1.0, min(1.0, low * 3.2 * envelope)) * 7000)
    return out


def _mix(samples: array.array, add: array.array, at: int) -> None:
    for i, s in enumerate(add):
        j = at + i
        if 0 <= j < len(samples):
            samples[j] = max(-32768, min(32767, samples[j] + s))


def stitch(storyboard: Storyboard, fmt: Format, log=print) -> tuple[Path, Path]:
    takes = []
    for scene in storyboard.scenes:
        sdir = scene_dir(storyboard, fmt, scene)
        path = sdir / "take.json"
        if not path.exists():
            raise FileNotFoundError(f"[{fmt.name}] {scene.label} has no take yet. Record it first.")
        takes.append((sdir, Take.load(path)))

    out_dir = storyboard.build_dir
    stem = f"{storyboard.id}-{fmt.slug}"
    audio_path = out_dir / f"{stem}.wav"
    srt_path = out_dir / f"{stem}.srt"
    mp4_path = out_dir / f"{stem}.mp4"

    # One entry per output frame: the screenshot on screen at that moment.
    # Inside a sped-up stretch, each output frame steps further through the take.
    schedule: list[Path] = []
    scene_starts: list[float] = []
    for sdir, take in takes:
        scene_starts.append(len(schedule) / FPS)
        frames = sorted(take.frames)
        shown, at = 0, 0.0
        first = len(schedule)
        while at < take.duration or len(schedule) == first:
            while shown + 1 < len(frames) and frames[shown + 1][0] <= at:
                shown += 1
            schedule.append(sdir / "frames" / frames[shown][1])
            at += _rate(take, at) / FPS
    total = len(schedule) / FPS

    samples = array.array("h", bytes(2 * round(total * SAMPLE_RATE)))
    cues = []
    for (sdir, take), offset in zip(takes, scene_starts):
        for mark in take.marks:
            begin = offset + _out_time(take, mark.start)
            with wave.open(mark.clip) as wf:
                clip = array.array("h", wf.readframes(wf.getnframes()))
            at = round(begin * SAMPLE_RATE)
            room = max(0, len(samples) - at)
            samples[at:at + min(len(clip), room)] = clip[:room]
            cues.append((begin, begin + mark.seconds, mark.text))
    if storyboard.sfx:
        sweep = _whoosh()
        for cut in scene_starts[1:]:
            _mix(samples, sweep, round((cut - 0.28) * SAMPLE_RATE))

    with wave.open(str(audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(samples.tobytes())

    srt_path.write_text(
        "\n".join(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, start=1)),
        encoding="utf-8",
    )

    w, h = fmt.width, fmt.height
    audio_in = ["-i", str(audio_path)]
    audio_map: list[str] = []
    if storyboard.music:
        music = storyboard.resolve(storyboard.music["file"])
        if not music.exists():
            raise FileNotFoundError(f"music file {music} not found")
        vol = float(storyboard.music.get("volume", 0.18))
        audio_in += ["-stream_loop", "-1", "-i", str(music)]
        fade_at = max(0.0, total - 1.5)
        audio_map = [
            "-filter_complex",
            "[1:a]aresample=48000,pan=stereo|c0=c0|c1=c0,asplit=2[voice][key];"
            f"[2:a]aresample=48000,volume={vol},afade=t=out:st={fade_at:.2f}:d=1.5[bed];"
            "[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=500[ducked];"
            "[voice][ducked]amix=inputs=2:normalize=0[aout]",
            "-map", "0:v", "-map", "[aout]",
        ]
    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "image2pipe", "-framerate", str(FPS), "-c:v", "png", "-i", "-",
        *audio_in,
        *audio_map,
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x080A0F,format=yuv420p",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k",
        "-t", f"{total:.3f}", "-movflags", "+faststart",
        str(mp4_path),
    ]
    log(f"[{fmt.name}] encoding {total:.1f} s ({len(schedule)} frames) to {mp4_path.name}")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    last_path, last_bytes = None, b""
    try:
        for path in schedule:
            if path != last_path:
                last_path, last_bytes = path, path.read_bytes()
            proc.stdin.write(last_bytes)
    finally:
        proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed (exit {proc.returncode})")
    return mp4_path, srt_path
