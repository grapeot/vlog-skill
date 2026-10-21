"""Timing between two media files and between a transcript and the picture.

`offsets` cross-correlates two audio tracks at several points. A rendered avatar video can keep the
uploaded audio sample for sample (offset 0 everywhere), or it can be stitched from scenes and drift
(in one production: 0 ms at 5 s, 92 ms at 500 s, 160 ms at 1000 s). Only in the first case can the
edit manifest's timeline drive the picture; otherwise transcribe the avatar video and time from that.

`anchors` resolves spoken phrases to times in a transcript, so picture events land on the words.
"""

from __future__ import annotations

import numpy as np

from .audio import load_audio

SR = 8000
_SKIP = set(" ，。？！；：、,.?!;:\"'“”‘’（）()")


def offset_at(reference: str, other: str, at: float, window: float = 30.0) -> dict:
    a = load_audio(reference, SR, 1, start=at, duration=window)
    b = load_audio(other, SR, 1, start=at, duration=window)
    n = min(len(a), len(b))
    if n < SR:
        raise ValueError(f"less than one second of audio at {at} s")
    a, b = a[:n].astype(np.float64), b[:n].astype(np.float64)
    c = np.fft.irfft(np.fft.rfft(a, 2 * n) * np.conj(np.fft.rfft(b, 2 * n)))
    lag = int(np.argmax(c))
    lag = lag if lag < n else lag - 2 * n
    corr = float(c.max() / (np.sqrt((a * a).sum() * (b * b).sum()) + 1e-12))
    # positive: the other file is late relative to the reference
    return {"at": at, "offset_ms": round(-lag * 1000 / SR, 1), "correlation": round(corr, 4)}


def offsets(reference: str, other: str, points: list[float], window: float = 30.0, tolerance_ms: float = 20.0) -> dict:
    rows = [offset_at(reference, other, p, window) for p in points]
    worst = max(abs(r["offset_ms"]) for r in rows)
    return {"reference": reference, "other": other, "points": rows, "max_abs_offset_ms": worst,
            "aligned": worst <= tolerance_ms and min(r["correlation"] for r in rows) > 0.9}


def anchors(words: list[dict], phrases: dict[str, str], after: float = 0.0, until: float | None = None) -> dict[str, float]:
    """First occurrence of each phrase starting at or after `after` (and before `until`), as the start
    time of its first word. Spaces and punctuation are ignored on both sides (aligner words carry no
    punctuation, so a phrase copied from the transcript text with its commas must still match). A phrase that is not found raises, so a
    reworded line cannot silently drift its picture beat."""
    def strip(s: str) -> str:
        return "".join(ch for ch in s if ch not in _SKIP)

    chars, owner = [], []
    for i, w in enumerate(words):
        for ch in strip(w["text"]):
            chars.append(ch)
            owner.append(i)
    text = "".join(chars)
    out, missing = {}, []
    for name, phrase in phrases.items():
        p = strip(phrase)
        pos, found = 0, None
        while True:
            k = text.find(p, pos)
            if k < 0:
                break
            t = words[owner[k]]["start"]
            if t >= after and (until is None or t < until):
                found = round(t, 3)
                break
            pos = k + 1
        if found is None:
            missing.append(name)
        else:
            out[name] = found
    if missing:
        raise KeyError(f"phrases not found in the transcript window: {', '.join(missing)}")
    return out
