"""Stitch the takes into one MP4 and one SRT per format.

Frames are lossless PNGs with the time each was drawn. For every 1/30 s of
the video, the stitch picks the frame that was on screen at that moment and
pipes it to ffmpeg, which encodes once to H.264 at exactly 30 fps. Scene
offsets come from the same frame count, and the narration is one WAV with
every clip placed where its beat started, so picture and voice cannot drift.

With an "audio" setting, the track is finished before the encode: mixed to
48 kHz stereo with any music and room tone, then normalised in two passes
(loudnorm measures, then applies one linear gain), so the integrated
loudness and true peak land where the setting says.
"""

import array
import json
import math
import random
import shutil
import subprocess
import wave
from pathlib import Path

from docdocs.captions import timings
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


def _resample(clip: array.array, src: int, dst: int) -> array.array:
    """Linear resampling, plenty for speech."""
    n = round(len(clip) * dst / src)
    out = array.array("h", bytes(2 * n))
    step = src / dst
    last = len(clip) - 1
    for i in range(n):
        x = i * step
        j = int(x)
        if j >= last:
            out[i] = clip[last]
        else:
            f = x - j
            out[i] = int(clip[j] * (1 - f) + clip[j + 1] * f)
    return out


def _whoosh(rate: int = SAMPLE_RATE, seconds: float = 0.55) -> array.array:
    """A soft, synthesized whoosh: filtered noise that swells and fades. No samples, no licence."""
    rng = random.Random(7)
    n = round(seconds * rate)
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


def _loudnorm_stats(stderr: str) -> dict:
    """The JSON block loudnorm prints at the end of a measuring pass."""
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start == -1 or end < start:
        raise RuntimeError(f"loudnorm printed no measurements:\n{stderr[-800:]}")
    return json.loads(stderr[start:end + 1])


def finish_audio(storyboard: Storyboard, voice: Path, total: float, out: Path, log=print) -> Path:
    """Mix the voice track to 48 kHz stereo with music and room tone, then normalise it in two passes."""
    spec = storyboard.audio or {}
    target, peak = float(spec.get("loudness", -16)), float(spec.get("truePeak", -1))
    inputs = ["-i", str(voice)]
    chains, mix = [], []
    if storyboard.music:
        music = storyboard.resolve(storyboard.music["file"])
        if not music.exists():
            raise FileNotFoundError(f"music file {music} not found")
        vol = float(storyboard.music.get("volume", 0.18))
        n = inputs.count("-i")
        inputs += ["-stream_loop", "-1", "-i", str(music)]
        chains += [
            "[0:a]aresample=48000,aformat=channel_layouts=stereo,asplit=2[voice][key]",
            f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={vol},"
            f"afade=t=out:st={max(0.0, total - 1.5):.2f}:d=1.5[bed]",
            "[bed][key]sidechaincompress=threshold=0.03:ratio=6:attack=30:release=500[ducked]",
        ]
        mix += ["[voice]", "[ducked]"]
    else:
        chains.append("[0:a]aresample=48000,aformat=channel_layouts=stereo[voice]")
        mix.append("[voice]")
    room = spec.get("roomTone")
    if room:
        gain = float(room.get("gain", -58))
        n = inputs.count("-i")
        if room.get("file"):
            source = storyboard.resolve(room["file"])
            if not source.exists():
                raise FileNotFoundError(f"room tone file {source} not found")
            inputs += ["-stream_loop", "-1", "-i", str(source)]
            chains.append(f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo,volume={gain}dB[room]")
        else:
            # Synthesized: brown noise, low-passed, far under the voice. A recorded room is better when there is one.
            inputs += ["-f", "lavfi", "-i", "anoisesrc=color=brown:sample_rate=48000:amplitude=0.5:seed=7"]
            chains.append(f"[{n}:a]aformat=channel_layouts=stereo,lowpass=f=1000,volume={gain}dB[room]")
        mix.append("[room]")
    if len(mix) > 1:
        chains.append(f"{''.join(mix)}amix=inputs={len(mix)}:normalize=0:duration=first[mix]")
    else:
        chains.append("[voice]anull[mix]")
    graph = ";".join(chains)
    norm = f"loudnorm=I={target}:TP={peak}:LRA=11"

    cmd = [ffmpeg_exe(), "-hide_banner", "-nostats", *inputs, "-filter_complex",
           f"{graph};[mix]{norm}:print_format=json[out]", "-map", "[out]", "-t", f"{total:.3f}", "-f", "null", "-"]
    measured = _loudnorm_stats(subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace").stderr)
    log(f"audio: measured {measured['input_i']} LUFS, true peak {measured['input_tp']} dBTP")
    apply = (f"{norm}:measured_I={measured['input_i']}:measured_TP={measured['input_tp']}"
             f":measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}"
             f":offset={measured['target_offset']}:linear=true:print_format=json")
    cmd = [ffmpeg_exe(), "-y", "-hide_banner", "-nostats", *inputs, "-filter_complex",
           f"{graph};[mix]{apply},aresample=48000[out]", "-map", "[out]", "-t", f"{total:.3f}",
           "-c:a", "pcm_s16le", "-ar", "48000", "-ac", "2", str(out)]
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if result.returncode != 0 or not out.exists():
        raise RuntimeError(f"ffmpeg could not finish the audio:\n{result.stderr[-800:]}")
    done = _loudnorm_stats(result.stderr)
    log(f"audio: {done['output_i']} LUFS, true peak {done['output_tp']} dBTP ({done['normalization_type']})")
    return out


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

    # The track runs at the voice's own rate (Piper 22.05 kHz, Kokoro 24 kHz).
    first = next((mk.clip for _, tk in takes for mk in tk.marks), None)
    rate = SAMPLE_RATE
    if first:
        with wave.open(first) as wf:
            rate = wf.getframerate()
    samples = array.array("h", bytes(2 * round(total * rate)))
    cues = []
    for (sdir, take), offset in zip(takes, scene_starts):
        for mark in take.marks:
            begin = offset + _out_time(take, mark.start)
            with wave.open(mark.clip) as wf:
                clip = array.array("h", wf.readframes(wf.getnframes()))
                if wf.getframerate() != rate:
                    clip = _resample(clip, wf.getframerate(), rate)
            at = round(begin * rate)
            room = max(0, len(samples) - at)
            samples[at:at + min(len(clip), room)] = clip[:room]
            if storyboard.srt == "lines":
                # The voice plays at normal speed even in a sped-up beat, so clip time is video time.
                for chunk in timings(mark.text, Path(mark.clip)):
                    a, b = chunk["times"][0][0], chunk["times"][-1][1]
                    cues.append((begin + a / 1000, begin + b / 1000, " ".join(chunk["words"])))
            else:
                cues.append((begin, begin + mark.seconds, mark.text))
    if storyboard.sfx:
        sweep = _whoosh(rate)
        for cut in scene_starts[1:]:
            _mix(samples, sweep, round((cut - 0.28) * rate))

    with wave.open(str(audio_path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(samples.tobytes())

    srt_path.write_text(
        "\n".join(f"{n}\n{_srt_time(a)} --> {_srt_time(b)}\n{text}\n" for n, (a, b, text) in enumerate(cues, start=1)),
        encoding="utf-8",
    )

    w, h = fmt.width, fmt.height
    audio_in = ["-i", str(audio_path)]
    audio_map: list[str] = []
    if storyboard.audio:
        final = finish_audio(storyboard, audio_path, total, out_dir / f"{stem}-final.wav", log)
        audio_in = ["-i", str(final)]
    elif storyboard.music:
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
        "-vf", f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=0x080A0F,setsar=1,format=yuv420p",
        "-r", str(FPS),
        "-c:v", "libx264", "-preset", "medium", "-profile:v", "high", "-crf", str(storyboard.crf),
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
