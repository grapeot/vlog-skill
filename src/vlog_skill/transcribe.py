"""Word-level transcription and the vlog.transcript/1 schema.

The acoustic engine is Qwen3-ASR with the Qwen3 forced aligner through mlx-qwen3-asr, which runs on
Apple Silicon only and is an optional extra. Any transcript that follows the schema can be used by
the rest of the pipeline, so other engines can be plugged in by converting their output.
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
import tempfile
from pathlib import Path

from .audio import DependencyError, ToolError, probe_duration, require_ffmpeg

SCHEMA = "vlog.transcript/1"
DEFAULT_MODEL = "Qwen/Qwen3-ASR-1.7B"
DEFAULT_ALIGNER = "Qwen/Qwen3-ForcedAligner-0.6B"
PUNCTUATION = " ，。？！；：、,.?!;:\"”’）)"
SENTENCE_END = set("。？！.?!")
CLAUSE_END = set("，；：、,;:")


def attach_punctuation(words: list[dict], text: str) -> list[dict]:
    """Copy the punctuation that follows each word in the full text onto the word as `punc`.

    Aligner words carry no punctuation; the edit pacing and the subtitle chunking need it.
    """
    pos = 0
    lowered = text.lower()
    for w in words:
        token = w["text"]
        idx = text.find(token, pos)
        if idx == -1 or idx - pos > 25:
            idx = lowered.find(token.lower(), pos)
        if idx != -1 and idx - pos <= 30:
            pos = idx + len(token)
            punc = ""
            while pos < len(text) and text[pos] in PUNCTUATION:
                punc += text[pos]
                pos += 1
            w["punc"] = punc.strip()
        else:
            w.setdefault("punc", "")
    return words


def punc_kind(punc: str) -> str:
    if any(ch in SENTENCE_END for ch in punc):
        return "period"
    if any(ch in CLAUSE_END for ch in punc):
        return "comma"
    return "none"


def normalize(raw: dict, media: str | None = None) -> dict:
    """Accept a vlog.transcript/1 document or a raw mlx-qwen3-asr dump and return the schema."""
    if raw.get("schema") == SCHEMA:
        return raw
    words_src = raw.get("words") or raw.get("segments") or []
    words = [
        {"text": str(w["text"]), "start": float(w["start"]), "end": float(w["end"])}
        for w in words_src
        if str(w.get("text", "")).strip()
    ]
    # Chunk texts carry the engine's punctuation per chunk; prefer them over the flattened text.
    chunks = raw.get("chunks") or []
    text = "".join(c.get("text", "") for c in chunks) if chunks else (raw.get("text") or "")
    attach_punctuation(words, text)
    return {
        "schema": SCHEMA,
        "media": media or raw.get("audio_path") or raw.get("media"),
        "duration_s": raw.get("duration_s"),
        "engine": raw.get("engine") or {"name": "mlx-qwen3-asr", "model": raw.get("model")},
        "language": raw.get("language"),
        "text": text,
        "words": words,
    }


def load_transcript(path: str | Path) -> dict:
    return normalize(json.loads(Path(path).read_text(encoding="utf-8")))


def _to_plain(x):
    if dataclasses.is_dataclass(x):
        return {k: _to_plain(v) for k, v in dataclasses.asdict(x).items()}
    if isinstance(x, dict):
        return {k: _to_plain(v) for k, v in x.items()}
    if isinstance(x, (list, tuple)):
        return [_to_plain(v) for v in x]
    if isinstance(x, (str, int, float, bool)) or x is None:
        return x
    return str(x)


def transcribe(
    media: str | Path,
    model: str = DEFAULT_MODEL,
    aligner: str = DEFAULT_ALIGNER,
    language: str | None = None,
    context: str = "",
) -> dict:
    """Transcribe an audio or video file to vlog.transcript/1 with word timestamps."""
    try:
        import mlx_qwen3_asr  # noqa: F401
    except ImportError as exc:
        raise DependencyError(
            "mlx-qwen3-asr is not installed; it needs Apple Silicon: uv pip install -e '.[asr]'. "
            "Alternatively produce a vlog.transcript/1 JSON with another engine."
        ) from exc
    import mlx_qwen3_asr as m

    require_ffmpeg()
    media = Path(media)
    if not media.is_file():
        raise FileNotFoundError(f"no such file: {media}")
    with tempfile.TemporaryDirectory() as tmp:
        # Always feed the engine a 16 kHz mono WAV: it handles video containers and odd codecs.
        wav = Path(tmp) / "audio.wav"
        proc = subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(media), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            raise ToolError(f"ffmpeg could not extract audio from {media}: {proc.stderr.strip()}")
        result = m.transcribe(
            str(wav),
            model=model,
            language=language,
            context=context,
            return_timestamps=True,
            return_chunks=True,
            forced_aligner=aligner,
        )
    raw = {k: _to_plain(getattr(result, k)) for k in dir(result) if not k.startswith("_") and not callable(getattr(result, k))}
    doc = normalize(raw, media=str(media))
    doc["duration_s"] = round(probe_duration(media), 3)
    doc["engine"] = {"name": "mlx-qwen3-asr", "model": model, "aligner": aligner}
    doc["language"] = language or raw.get("language")
    doc["truncated"] = bool(raw.get("truncated", False))
    return doc
