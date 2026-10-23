"""Word timings for captions, from the voice clip itself.

Piper does not report word times, so each word gets a share of the spoken
part of its clip (from the first to the last sound above the noise floor),
weighted by its length, with extra room after punctuation. Close enough for
a word to light up while it is said.
"""

import array
import re
import wave
from pathlib import Path

MAX_WORDS = 5
MAX_CHARS = 30


def speech_bounds(path: Path, floor: float = 0.04) -> tuple[float, float]:
    """Seconds where speech starts and ends in a 16-bit mono WAV."""
    with wave.open(str(path)) as wf:
        rate = wf.getframerate()
        samples = array.array("h", wf.readframes(wf.getnframes()))
    if not samples:
        return 0.0, 0.0
    window = max(1, rate // 100)  # 10 ms
    peak = max(abs(s) for s in samples) or 1
    loud = [
        i for i in range(0, len(samples), window)
        if max(abs(s) for s in samples[i:i + window]) > peak * floor
    ]
    if not loud:
        return 0.0, len(samples) / rate
    return loud[0] / rate, min(len(samples), loud[-1] + window) / rate


def _weight(word: str) -> float:
    w = len(re.sub(r"[^\w]", "", word)) + 2
    if re.search(r"[.!?]$", word):
        w += 5
    elif re.search(r"[,;:]$", word):
        w += 3
    return w


def chunk_words(words: list[str]) -> list[list[int]]:
    """Group word indexes into short caption lines, breaking after punctuation when possible."""
    groups, current, chars = [], [], 0
    for i, word in enumerate(words):
        # One word over the limit is fine when it closes the phrase ("too small,").
        closes = bool(re.search(r"[.!?,;:]$", word))
        limit = MAX_WORDS + 1 if closes else MAX_WORDS
        if current and (len(current) >= limit or chars + len(word) > MAX_CHARS + (6 if closes else 0)):
            groups.append(current)
            current, chars = [], 0
        current.append(i)
        chars += len(word) + 1
        if re.search(r"[.!?,;:]$", word) and len(current) >= 2:
            groups.append(current)
            current, chars = [], 0
    if current:
        groups.append(current)
    return groups


def timings(text: str, wav: Path, stretch: float = 1.0) -> list[dict]:
    """Caption chunks with per-word [start, end] in ms from the beat start, scaled by stretch."""
    words = text.split()
    if not words:
        return []
    start, end = speech_bounds(wav)
    weights = [_weight(w) for w in words]
    total = sum(weights)
    spans, at = [], start
    for w in weights:
        length = (end - start) * w / total
        spans.append((at, at + length))
        at += length
    chunks = []
    for group in chunk_words(words):
        chunks.append({
            "words": [words[i] for i in group],
            "times": [[round(spans[i][0] * 1000 * stretch), round(spans[i][1] * 1000 * stretch)] for i in group],
        })
    return chunks
