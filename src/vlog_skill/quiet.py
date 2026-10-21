"""Find quiet gaps in a recording, so cut edges land between syllables rather than inside them."""

from __future__ import annotations

from pathlib import Path

import numpy as np

from .audio import load_audio, rms_db

ANALYSIS_SR = 16000
HOP_S = 0.01


def quiet_runs_from_envelope(
    db: np.ndarray,
    t0: float,
    threshold_db: float = -40.0,
    min_duration_s: float = 0.03,
    hop_s: float = HOP_S,
) -> list[dict]:
    """Runs of consecutive windows below threshold_db, as absolute times."""
    runs: list[dict] = []
    start = None
    for i, level in enumerate(np.append(db, np.float32(np.inf))):  # sentinel closes a trailing run
        quiet = level < threshold_db
        if quiet and start is None:
            start = i
        elif not quiet and start is not None:
            if (i - start) * hop_s >= min_duration_s - 1e-9:
                seg = db[start:i]
                runs.append(
                    {
                        "start": round(t0 + start * hop_s, 3),
                        "end": round(t0 + i * hop_s, 3),
                        "duration": round((i - start) * hop_s, 3),
                        "min_db": round(float(seg.min()), 1),
                        "center": round(t0 + (start + i) * hop_s / 2, 3),
                    }
                )
            start = None
    return runs


def find_quiet_runs(
    path: str | Path,
    start: float,
    end: float,
    threshold_db: float = -40.0,
    min_duration_s: float = 0.03,
) -> dict:
    if end <= start:
        raise ValueError("end must be greater than start")
    x = load_audio(path, ANALYSIS_SR, 1, start=start, duration=end - start)
    db = rms_db(x, ANALYSIS_SR, HOP_S)
    runs = quiet_runs_from_envelope(db, start, threshold_db, min_duration_s)
    return {
        "audio": str(path),
        "window": {"start": start, "end": end},
        "threshold_db": threshold_db,
        "runs": runs,
        "envelope_db": [round(float(v), 1) for v in db],
        "envelope_hop_s": HOP_S,
    }
