"""Stitch the takes into one MP4 and one SRT per format.

Frames are lossless PNGs with the time each was drawn. The video is the
frames held for exactly as long as they were on screen, encoded once to
H.264. The narration is one WAV with every clip placed where its beat
started, so picture and voice cannot drift.
"""

import array
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
    concat = out_dir / f"{stem}.frames.txt"
    audio_path = out_dir / f"{stem}.wav"
    srt_path = out_dir / f"{stem}.srt"
    mp4_path = out_dir / f"{stem}.mp4"

    lines = ["ffconcat version 1.0"]
    total = sum(t.duration for _, t in takes)
    samples = array.array("h", bytes(2 * round(total * SAMPLE_RATE)))
    cues = []
    offset = 0.0
    last_frame = None
    for sdir, take in takes:
        frames = sorted(take.frames)
        for i, (at, name) in enumerate(frames):
            start = 0.0 if i == 0 else at
            end = frames[i + 1][0] if i + 1 < len(frames) else take.duration
            if end - start <= 0:
                continue
            last_frame = (sdir / "frames" / name).as_posix()
            lines.append(f"file '{last_frame}'")
            lines.append(f"duration {end - start:.4f}")
        for mark in take.marks:
            begin = offset + mark.start
            with wave.open(mark.clip) as wf:
                clip = array.array("h", wf.readframes(wf.getnframes()))
            at = round(begin * SAMPLE_RATE)
            room = len(samples) - at
            samples[at:at + min(len(clip), room)] = clip[:room]
            cues.append((begin, begin + mark.seconds, mark.text))
        offset += take.duration
    if last_frame:
        lines.append(f"file '{last_frame}'")  # the concat demuxer drops the last duration otherwise
    concat.write_text("\n".join(lines) + "\n", encoding="utf-8")

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
    cmd = [
        ffmpeg_exe(), "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0", "-i", str(concat),
        "-i", str(audio_path),
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x080A0F,format=yuv420p",
        "-fps_mode", "cfr", "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-crf", "18",
        "-c:a", "aac", "-b:a", "160k",
        "-t", f"{total:.3f}", "-movflags", "+faststart",
        str(mp4_path),
    ]
    log(f"[{fmt.name}] encoding {total:.1f} s to {mp4_path.name}")
    subprocess.run(cmd, check=True)
    return mp4_path, srt_path
