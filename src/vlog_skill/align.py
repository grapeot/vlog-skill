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
_SKIP = set(" \u3000，。？！；：、,.?!;:\"'“”‘’（）()…—《》「」【】·")


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


def _xcorr_lag(a: np.ndarray, b: np.ndarray) -> tuple[int, np.ndarray]:
    """Lag k maximizing sum a[t] * b[t - k]: a[t] lines up with b[t - k]."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    c = np.fft.irfft(np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n)), n)
    k = int(np.argmax(np.abs(c)))
    return (k if k < n // 2 else k - n), c


def global_offset(reference: str, other: str, points: int = 5, window: float = 8.0,
                  tolerance_ms: float = 20.0) -> dict:
    """Offset between two recordings that may have started many seconds apart (camera, screen, voice
    memo of the same session). Searches the whole overlap once, then refines at several points spread
    over the overlap and reports drift. `start_delta_s` is other's start minus reference's start in wall
    clock time, so reference_time = other_time + start_delta_s."""
    a = load_audio(reference, SR, 1).astype(np.float64)
    b = load_audio(other, SR, 1).astype(np.float64)
    if min(len(a), len(b)) < 2 * SR:
        raise ValueError("need at least two seconds of audio in both files")
    a -= a.mean()
    b -= b.mean()
    lag, c = _xcorr_lag(a, b)
    mag = np.abs(c)
    peak = float(mag[lag % len(c)])
    guard = int(0.5 * SR)
    masked = mag.copy()
    for k in range(lag - guard, lag + guard + 1):
        masked[k % len(c)] = 0.0
    confidence = peak / (float(masked.max()) + 1e-12)
    delta = lag / SR  # reference index t lines up with other index t - lag

    # overlap on the reference clock: other covers [delta, delta + len(b)/SR]
    lo = max(0.0, delta) + 0.5
    hi = min(len(a) / SR, delta + len(b) / SR) - window - 0.5
    rows = []
    if hi > lo:
        for t in np.linspace(lo, hi, max(1, points)):
            s0 = int(t * SR)
            seg_a = a[s0:s0 + int(window * SR)]
            o0 = int((t - delta - 0.25) * SR)
            seg_b = b[max(0, o0):max(0, o0) + int((window + 0.5) * SR)]
            k, _ = _xcorr_lag(seg_a, seg_b)
            local = (s0 - (max(0, o0) - k)) / SR  # reference time minus matching other time
            # local should equal t - (t - delta) = delta; the residual is drift or a bad match
            res_ms = (local - delta) * 1000.0
            j = max(0, o0) - k  # other sample aligned with reference sample s0
            seg_m = b[max(0, j):max(0, j) + len(seg_a)]
            n = min(len(seg_a), len(seg_m))
            corr = float(abs(np.dot(seg_a[:n], seg_m[:n])) / (np.sqrt((seg_a[:n] ** 2).sum() * (seg_m[:n] ** 2).sum()) + 1e-12)) if n else 0.0
            rows.append({"at": round(float(t), 2), "residual_ms": round(res_ms, 2), "correlation": round(corr, 4)})
    drift = 0.0
    if len(rows) >= 2:
        ts = np.array([r["at"] for r in rows])
        rs = np.array([r["residual_ms"] for r in rows])
        drift = float(np.polyfit(ts / 60.0, rs, 1)[0])
    worst = max((abs(r["residual_ms"]) for r in rows), default=0.0)
    ok = bool(rows) and confidence > 3 and worst <= tolerance_ms and min(r["correlation"] for r in rows) > 0.9
    return {"reference": reference, "other": other, "start_delta_s": round(delta, 4),
            "meaning": "reference_time = other_time + start_delta_s (negative: other started earlier)",
            "confidence": round(confidence, 2), "points": rows, "drift_ms_per_min": round(drift, 3),
            "max_abs_residual_ms": round(worst, 2), "aligned": ok}


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
        if not p:
            raise ValueError(f"anchor {name!r}: phrase {phrase!r} is empty once spaces and punctuation are removed")
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
