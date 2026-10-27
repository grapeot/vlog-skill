"""Timing between two media files and between a transcript and the picture.

`offsets` cross-correlates two audio tracks at several points; `global_offset` handles recordings that
started far apart (camera and screen of the same session) and measures drift. A rendered avatar video can keep the
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


ENV_SR = 100  # 10 ms energy envelope for the coarse search
HIGHPASS_HZ = 150.0  # removes mains hum and rumble, which otherwise correlate at any lag


def _highpass(x: np.ndarray, sr: int, cutoff: float = HIGHPASS_HZ) -> np.ndarray:
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1.0 / sr) < cutoff] = 0.0
    return np.fft.irfft(spec, len(x)).astype(np.float32)


def _envelope(x: np.ndarray, sr: int) -> np.ndarray:
    hop = sr // ENV_SR
    n = len(x) // hop
    frames = x[: n * hop].astype(np.float64).reshape(n, hop)
    env = np.log(np.sqrt((frames * frames).mean(axis=1)) + 1e-6)
    return env - env.mean()


def _xcorr(a: np.ndarray, b: np.ndarray, phat: bool = False) -> tuple[int, np.ndarray]:
    """Lag k maximizing sum a[t] * b[t - k]: a[t] lines up with b[t - k]. With `phat`, the cross
    spectrum is whitened (GCC-PHAT), which keeps tonal noise from dominating the peak."""
    n = 1 << int(np.ceil(np.log2(len(a) + len(b))))
    cross = np.fft.rfft(a, n) * np.conj(np.fft.rfft(b, n))
    if phat:
        cross /= np.abs(cross) + 1e-12
    c = np.fft.irfft(cross, n)
    k = int(np.argmax(np.abs(c)))
    return (k if k < n // 2 else k - n), c


def global_offset(reference: str, other: str, points: int = 5, window: float = 8.0,
                  tolerance_ms: float = 20.0) -> dict:
    """Offset between two recordings that may have started many seconds apart (camera, screen, voice
    memo of the same session). A coarse search over the whole overlap runs on a high-passed 10 ms
    energy envelope (insensitive to hum and to clock drift), then each refinement point is matched on
    high-passed audio with GCC-PHAT, and a line (offset + drift) is fitted through the points.

    `start_delta_s` is other's start minus reference's start in wall-clock time at the start of the
    reference: reference_time = other_time + start_delta_s + drift_ms_per_min / 60000 * reference_time.
    The `--at` mode reports the opposite sign (`offset_ms` > 0 when other is late), so
    start_delta_s = -offset_ms / 1000 for files without drift."""
    if points < 1:
        raise ValueError("points must be at least 1")
    if window <= 0:
        raise ValueError("window must be positive")
    a = _highpass(load_audio(reference, SR, 1), SR)
    b = _highpass(load_audio(other, SR, 1), SR)
    base = {"reference": reference, "other": other,
            "meaning": "reference_time = other_time + start_delta_s (+ drift); negative: other started earlier; "
                       "--at mode uses the opposite sign (start_delta_s = -offset_ms/1000)"}
    if min(len(a), len(b)) < (window + 1.0) * SR:
        return {**base, "start_delta_s": None, "confidence": 0.0, "points": [], "drift_ms_per_min": None,
                "max_abs_residual_ms": None, "aligned": False,
                "reason": f"a file is shorter than window + 1 s ({window + 1.0:.1f} s)"}

    ea, eb = _envelope(a, SR), _envelope(b, SR)
    _, c = _xcorr(ea, eb)
    mag = np.abs(c)
    guard = int(0.5 * ENV_SR)
    candidates, peaks = [], []
    masked = mag.copy()
    for _ in range(3):  # the speech envelope is rhythmic: keep the best few peaks, let refinement choose
        k = int(np.argmax(masked))
        if masked[k] <= 0:
            break
        candidates.append(k if k < len(c) // 2 else k - len(c))
        peaks.append(float(masked[k]))
        masked[np.arange(k - guard, k + guard + 1) % len(c)] = 0.0
    coarse_confidence = peaks[0] / (peaks[1] + 1e-12) if len(peaks) > 1 else float("inf")
    del c, mag, masked

    w, margin, pguard = int(window * SR), int(0.5 * SR), int(0.05 * SR)

    def refine(coarse: float):
        # overlap on the reference clock: other covers [coarse, coarse + len(b)/SR]
        lo = max(0.0, coarse) + 0.5
        hi = min(len(a) / SR, coarse + len(b) / SR) - window - 0.5
        if hi < lo:
            return None
        times = [(lo + hi) / 2.0] if points == 1 else list(np.linspace(lo, hi, points))
        rows = []
        for t in times:
            s0 = int(t * SR)
            seg_a = a[s0:s0 + w]
            ob = max(0, int((t - coarse) * SR) - margin)
            seg_b = b[ob:ob + w + 2 * margin]
            k, cc = _xcorr(seg_a, seg_b, phat=True)
            m = np.abs(cc)
            top = float(m[k % len(cc)])
            m[np.arange(k - pguard, k + pguard + 1) % len(cc)] = 0.0
            sharp = top / (float(m.max()) + 1e-12)
            local = (s0 - ob + k) / SR  # reference time - other time at this point
            j = ob - k
            seg_m = b[max(0, j):max(0, j) + len(seg_a)]
            n = min(len(seg_a), len(seg_m), 2 * SR)  # 2 s: clock drift inside the window would smear it
            c0 = max(0, (min(len(seg_a), len(seg_m)) - n) // 2)
            x, y = seg_a[c0:c0 + n].astype(np.float64), seg_m[c0:c0 + n].astype(np.float64)
            corr = abs(float(np.dot(x, y))) / (float(np.sqrt(np.dot(x, x) * np.dot(y, y))) + 1e-12) if n else 0.0
            rows.append({"at": round(float(t), 2), "delta_s": local, "correlation": round(corr, 4),
                         "peak_sharpness": round(sharp, 2)})
        return rows

    best = None
    for k in candidates:
        rows = refine(k / ENV_SR)
        if rows and (best is None or np.median([r["correlation"] for r in rows]) > np.median([r["correlation"] for r in best])):
            best = rows
    if best is None:
        return {**base, "start_delta_s": round(candidates[0] / ENV_SR, 4) if candidates else None,
                "confidence": 0.0, "coarse_confidence": round(coarse_confidence, 2), "points": [],
                "drift_ms_per_min": None, "max_abs_residual_ms": None, "aligned": False,
                "reason": f"overlap shorter than window + 1 s ({window + 1.0:.1f} s); lower --window"}
    # place the points again from the refined offset: the coarse peak can be off by a few hundred ms
    rows = refine(float(np.median([r["delta_s"] for r in best]))) or best
    confidence = float(np.median([r["peak_sharpness"] for r in rows]))

    ts = np.array([r["at"] for r in rows])
    ds = np.array([r["delta_s"] for r in rows])
    if len(rows) >= 2:
        slope, intercept = np.polyfit(ts, ds, 1)
        drift = float(slope * 60000.0)
    else:
        slope, intercept, drift = 0.0, float(ds[0]), None
    fit = intercept + slope * ts
    for r, f in zip(rows, fit):
        r["residual_ms"] = round((r["delta_s"] - f) * 1000.0, 2)
        r["delta_s"] = round(r["delta_s"], 4)
    worst = max(abs(r["residual_ms"]) for r in rows)
    # a wrong match has no sharp peak and near-zero correlation; a right one at a fractional-sample
    # offset can still correlate well below 1 at an integer lag, so judge the median, not every point
    median_corr = float(np.median([r["correlation"] for r in rows]))
    ok = confidence > 3 and worst <= tolerance_ms and median_corr > 0.5
    out = {**base, "start_delta_s": round(float(intercept), 4), "confidence": round(confidence, 2),
           "coarse_confidence": round(coarse_confidence, 2), "points": rows,
           "drift_ms_per_min": None if drift is None else round(drift, 3),
           "max_abs_residual_ms": round(worst, 2), "aligned": bool(ok)}
    if not ok:
        out["reason"] = ("low confidence: the refined correlation peaks are not sharp (median peak_sharpness <= 3)" if confidence <= 3 else
                         "median refinement correlation is 0.5 or below" if median_corr <= 0.5 else
                         "a refinement point misses the fitted offset-plus-drift line by more than the tolerance")
    return out


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
