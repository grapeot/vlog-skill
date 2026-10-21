"""Synthetic speech-like audio and matching transcripts for offline tests.

Each "word" is a short tone burst at its own pitch over a low noise floor, so tests can check
which words survived an edit by measuring the dominant frequency at the expected output time.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np

SR = 48000


def make_recording(words: list[tuple[str, float, float, float, str]], total_s: float, seed: int = 0) -> np.ndarray:
    """words: (text, start, end, freq_hz, punc). Returns stereo float32 at SR."""
    rng = np.random.default_rng(seed)
    n = int(total_s * SR)
    mono = (rng.standard_normal(n) * 10 ** (-62 / 20)).astype(np.float32)  # room tone near -62 dBFS
    for _, start, end, freq, _ in words:
        i0, i1 = int(start * SR), int(end * SR)
        t = np.arange(i1 - i0) / SR
        env = np.minimum(1.0, np.minimum(t, t[::-1]) / 0.01)  # 10 ms ramps
        mono[i0:i1] += (0.3 * np.sin(2 * np.pi * freq * t) * env).astype(np.float32)
    return np.stack([mono, mono], axis=1)


def transcript(words, media: str = "raw.wav") -> dict:
    return {
        "schema": "vlog.transcript/1",
        "media": media,
        "duration_s": None,
        "engine": {"name": "synthetic"},
        "language": "Chinese",
        "text": "".join(w[0] + w[4] for w in words),
        "words": [{"text": w[0], "start": w[1], "end": w[2], "punc": w[4]} for w in words],
    }


def write_project(tmp: Path, words, total_s: float, cuts: list[dict], **plan_extra) -> Path:
    from vlog_skill.audio import write_wav

    write_wav(tmp / "raw.wav", make_recording(words, total_s), SR)
    (tmp / "raw.json").write_text(json.dumps(transcript(words), ensure_ascii=False), encoding="utf-8")
    plan = {
        "schema": "vlog.edit_plan/1",
        "source_audio": "raw.wav",
        "transcript": "raw.json",
        "output_wav": "out/edited.wav",
        "manifest": "out/manifest.json",
        "sample_rate": SR,
        "room_tone": {"start": 0.0, "end": 0.9},
        "cuts": cuts,
    } | plan_extra
    path = tmp / "plan.json"
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    return path


def dominant_freq(x: np.ndarray, sr: int = SR) -> float:
    spec = np.abs(np.fft.rfft(x * np.hanning(len(x))))
    return float(np.fft.rfftfreq(len(x), 1 / sr)[int(np.argmax(spec))])
