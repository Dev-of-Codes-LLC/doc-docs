"""Synthesize sentences with Kokoro. Run as its own process; DOC Docs never imports it.

Kokoro's weights are Apache-2.0 and kokoro-onnx is MIT, but its phonemizer
and espeak-ng are GPL-3.0. Keeping them in a separate process keeps DOC Docs
itself MIT, the same way it runs Piper and ffmpeg.

Reads one JSON object on stdin:
    {"model": "...onnx", "voices": "...bin", "voice": "am_michael", "speed": 1.0,
     "lang": "en-us", "items": [{"text": "...", "out": "...wav"}]}
and writes one 16-bit mono WAV per item at Kokoro's own rate (24 kHz).
"""

import json
import sys
import wave


def main() -> int:
    job = json.load(sys.stdin)
    try:
        import numpy as np
        from kokoro_onnx import Kokoro
    except ImportError:
        print("kokoro-onnx is not installed. Run: pip install kokoro-onnx", file=sys.stderr)
        return 2
    kokoro = Kokoro(job["model"], job["voices"])
    for n, item in enumerate(job["items"], start=1):
        samples, rate = kokoro.create(item["text"], voice=job["voice"], speed=float(job.get("speed", 1.0)),
                                      lang=job.get("lang", "en-us"))
        pcm = (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()
        with wave.open(item["out"], "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(rate)
            wf.writeframes(pcm)
        print(f"{n}/{len(job['items'])}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
