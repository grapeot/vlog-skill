"""SRT subtitles from a word-level transcript, with a glossary for mis-recognized terms."""

from __future__ import annotations

import re

from .transcribe import CLAUSE_END, SENTENCE_END

CJK = re.compile(r"[一-鿿]")
TRAILING_DROP = "，。、；：,;:"


def _width(text: str) -> float:
    """CJK characters count 1; Latin letters and digits count 0.5, so mixed lines balance."""
    return sum(1.0 if CJK.match(ch) else (0.5 if not ch.isspace() else 0.25) for ch in text)


def _needs_space(prev_word: str, word: str) -> bool:
    """Latin words are separated by a space even when punctuation follows the previous word."""
    return bool(prev_word and word and prev_word[-1].isascii() and prev_word[-1].isalnum()
                and word[0].isascii() and word[0].isalnum())


def apply_glossary(text: str, glossary: dict[str, str]) -> str:
    for wrong in sorted(glossary, key=len, reverse=True):
        text = text.replace(wrong, glossary[wrong])
    return text


def build_cues(words: list[dict], max_width: float = 22.0, min_duration_s: float = 0.8, glossary: dict | None = None) -> list[dict]:
    """Chunk at punctuation, never across a sentence end, at most max_width per cue."""
    glossary = glossary or {}
    cues: list[dict] = []
    cur: list[dict] = []
    text = ""

    def width_with(extra: str) -> float:
        return _width(apply_glossary(text + extra, glossary))

    def flush():
        nonlocal cur, text
        if cur:
            shown = apply_glossary(text, glossary).strip().rstrip(TRAILING_DROP).strip()
            if shown:
                cues.append({"start": cur[0]["start"], "end": cur[-1]["end"], "text": shown})
        cur, text = [], ""

    for w in words:
        word = w["text"].strip()
        if not word:
            continue
        piece = word + w.get("punc", "")
        sep = " " if cur and _needs_space(cur[-1]["text"].strip(), word) else ""
        if cur and width_with(sep + piece) > max_width:
            flush()
            sep = ""
        cur.append(w)
        text += sep + piece
        punc = w.get("punc", "")
        if any(ch in SENTENCE_END for ch in punc):
            flush()
        elif any(ch in CLAUSE_END for ch in punc) and width_with("") >= max_width * 0.6:
            flush()
    flush()

    for i, c in enumerate(cues):
        nxt = cues[i + 1]["start"] if i + 1 < len(cues) else None
        end = max(c["end"], c["start"] + min_duration_s)
        if nxt is not None:
            end = min(end, nxt - 0.01)
        end = max(end, c["start"] + 0.05)
        if nxt is not None:  # cues never overlap, even when two start almost together
            end = min(end, nxt)
        c["end"] = end
    return cues


def _srt_time(t: float) -> str:
    ms = int(round(t * 1000))  # integer milliseconds avoid "00:01:41,1000"
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(cues: list[dict]) -> str:
    blocks = [f"{i}\n{_srt_time(c['start'])} --> {_srt_time(c['end'])}\n{c['text']}\n" for i, c in enumerate(cues, 1)]
    return "\n".join(blocks)
