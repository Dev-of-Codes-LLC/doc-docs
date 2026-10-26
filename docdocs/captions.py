"""Word timings for captions and anchors, from the voice clip itself.

Neither Piper nor Kokoro reports word times. So each phrase (the words up to
a comma, colon or full stop) is matched to a stretch of sound in the clip:
a voice pauses at its commas, and those pauses show as short silences. Each
word then gets a share of its phrase's stretch, weighted by its length. When
the silences do not line up with the punctuation, the words share the whole
spoken part instead. Close enough for a word to light up while it is said,
and for a picture to land on the word that names it.
"""

import array
import re
import wave
from pathlib import Path

MAX_WORDS = 5
MAX_CHARS = 30


GAP_MIN_S = 0.05  # a silence this long inside the speech can be a phrase break


def _loudness(path: Path, floor: float) -> tuple[list[bool], float]:
    """Whether each 10 ms window of a 16-bit mono WAV is above the noise floor, and the clip's length."""
    with wave.open(str(path)) as wf:
        rate = wf.getframerate()
        samples = array.array("h", wf.readframes(wf.getnframes()))
    if not samples:
        return [], 0.0
    window = max(1, rate // 100)
    peak = max(abs(s) for s in samples) or 1
    loud = [max(abs(s) for s in samples[i:i + window]) > peak * floor for i in range(0, len(samples), window)]
    return loud, len(samples) / rate


def silences(path: Path, floor: float = 0.04) -> list[tuple[float, float]]:
    """The silent stretches inside the speech, (start, end) in seconds, at least GAP_MIN_S long."""
    loud, _ = _loudness(path, floor)
    gaps, run = [], None
    started = False
    for k, on in enumerate(loud):
        if on:
            if run is not None and started and (k - run) / 100 >= GAP_MIN_S:
                gaps.append((run / 100, k / 100))
            run, started = None, True
        elif run is None:
            run = k
    return gaps


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


def _spread(indexes: list[int], weights: list[float], start: float, end: float, spans: dict) -> None:
    total = sum(weights[i] for i in indexes) or 1
    at = start
    for i in indexes:
        length = (end - start) * weights[i] / total
        spans[i] = (at, at + length)
        at += length


def word_spans(words: list[str], wav: Path) -> list[tuple[float, float]]:
    """(start, end) in seconds for each word, phrases snapped to the clip's pauses where they line up."""
    start, end = speech_bounds(wav)
    weights = [_weight(w) for w in words]
    phrases, current = [], []
    for i, word in enumerate(words):
        current.append(i)
        if re.search(r"[.!?,;:]$", word) and i < len(words) - 1:
            phrases.append(current)
            current = []
    if current:
        phrases.append(current)
    spans: dict[int, tuple[float, float]] = {}
    gaps = [g for g in silences(wav) if start < g[0] and g[1] < end]
    if len(phrases) > 1 and gaps:
        # Where each break would fall if words shared the speech by weight; take the
        # nearest unused pause after the last one, if it is close enough to be that break.
        total = sum(weights)
        breaks, used_until, ok = [], start, True
        done = 0.0
        for phrase in phrases[:-1]:
            done += sum(weights[i] for i in phrase)
            expected = start + (end - start) * done / total
            near = [g for g in gaps if g[0] >= used_until]
            if not near:
                ok = False
                break
            gap = min(near, key=lambda g: abs((g[0] + g[1]) / 2 - expected))
            if abs((gap[0] + gap[1]) / 2 - expected) > max(0.45, 0.15 * (end - start)):
                ok = False
                break
            breaks.append(gap)
            used_until = gap[1]
        if ok:
            edges = [start] + [x for g in breaks for x in g] + [end]
            for n, phrase in enumerate(phrases):
                _spread(phrase, weights, edges[2 * n], edges[2 * n + 1], spans)
            return [spans[i] for i in range(len(words))]
    _spread(list(range(len(words))), weights, start, end, spans)
    return [spans[i] for i in range(len(words))]


def timings(text: str, wav: Path, stretch: float = 1.0) -> list[dict]:
    """Caption chunks with per-word [start, end] in ms from the beat start, scaled by stretch."""
    words = text.split()
    if not words:
        return []
    spans = word_spans(words, wav)
    chunks = []
    for group in chunk_words(words):
        chunks.append({
            "words": [words[i] for i in group],
            "times": [[round(spans[i][0] * 1000 * stretch), round(spans[i][1] * 1000 * stretch)] for i in group],
        })
    return chunks
