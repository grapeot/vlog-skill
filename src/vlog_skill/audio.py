"""Audio I/O through ffmpeg, RMS envelopes, and loudness measurement."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import numpy as np


class DependencyError(RuntimeError):
    """A required external program, optional Python package, or credential is missing."""


class ToolError(RuntimeError):
    """An external tool (ffmpeg, ffprobe) ran and failed; the message carries its stderr."""


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise DependencyError(f"{tool} not found on PATH")


def require_file(path: str | Path) -> None:
    if not Path(path).is_file():
        raise FileNotFoundError(f"no such file: {path}")


def probe_duration(path: str | Path) -> float:
    require_ffmpeg()
    require_file(path)
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    if out.returncode != 0:
        raise ToolError(f"ffprobe failed on {path}: {out.stderr.strip()}")
    return float(out.stdout.strip())


def load_audio(
    path: str | Path,
    sr: int,
    channels: int,
    start: float | None = None,
    duration: float | None = None,
) -> np.ndarray:
    """Decode any media file to float32 samples, shape (n,) for mono or (n, channels)."""
    require_ffmpeg()
    require_file(path)
    cmd = ["ffmpeg", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.4f}"]
    if duration is not None:
        cmd += ["-t", f"{duration:.4f}"]
    cmd += ["-i", str(path), "-vn", "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        raise ToolError(f"ffmpeg could not decode {path}: {proc.stderr.decode(errors='replace').strip()}")
    x = np.frombuffer(proc.stdout, dtype="<f4")
    if channels > 1:
        x = x.reshape(-1, channels)
    return x


def write_wav(path: str | Path, samples: np.ndarray, sr: int) -> None:
    """Write float32 samples as 16-bit PCM WAV."""
    require_ffmpeg()
    channels = 1 if samples.ndim == 1 else samples.shape[1]
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        [
            "ffmpeg", "-y", "-v", "error",
            "-f", "f32le", "-ar", str(sr), "-ac", str(channels), "-i", "-",
            "-c:a", "pcm_s16le", str(path),
        ],
        input=np.ascontiguousarray(samples, dtype="<f4").tobytes(),
        capture_output=True,
    )
    if proc.returncode != 0:
        raise ToolError(f"ffmpeg could not write {path}: {proc.stderr.decode(errors='replace').strip()}")


def encode_m4a(wav_path: str | Path, m4a_path: str | Path, bitrate: str = "256k") -> None:
    require_ffmpeg()
    Path(m4a_path).parent.mkdir(parents=True, exist_ok=True)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(wav_path), "-c:a", "aac", "-b:a", bitrate, str(m4a_path)],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ToolError(f"ffmpeg could not encode {m4a_path}: {proc.stderr.strip()}")


def measure_loudness(path: str | Path) -> dict:
    """Integrated loudness, loudness range and true peak from ffmpeg's ebur128 filter."""
    require_ffmpeg()
    proc = subprocess.run(
        ["ffmpeg", "-nostats", "-i", str(path), "-af", "ebur128=peak=true", "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise ToolError(f"ffmpeg ebur128 failed on {path}: {proc.stderr.strip()[-2000:]}")
    summary = proc.stderr[proc.stderr.rfind("Summary:"):] if "Summary:" in proc.stderr else proc.stderr

    def grab(pattern: str) -> float | None:
        m = re.search(pattern, summary)
        return float(m.group(1)) if m else None

    return {
        "integrated_lufs": grab(r"I:\s+(-?[\d.]+) LUFS"),
        "loudness_range_lu": grab(r"LRA:\s+(-?[\d.]+) LU"),
        "true_peak_dbfs": grab(r"Peak:\s+(-?[\d.]+) dBFS"),
    }


def rms_db(samples: np.ndarray, sr: int, hop_s: float = 0.01) -> np.ndarray:
    """RMS level in dBFS per non-overlapping window of hop_s seconds (mono input)."""
    w = max(1, int(round(hop_s * sr)))
    n = len(samples) // w
    if n == 0:
        return np.zeros(0, dtype=np.float32)
    frames = samples[: n * w].reshape(n, w).astype(np.float64)
    return (20.0 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-9)).astype(np.float32)
