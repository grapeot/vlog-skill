"""SRT subtitles from a word-level transcript, with a glossary for mis-recognized terms."""

from __future__ import annotations

import re

import numpy as np

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


def _join_words(words: list[dict]) -> str:
    text, prev = "", ""
    for w in words:
        word = w["text"].strip()
        if not word:
            continue
        text += (" " if _needs_space(prev, word) else "") + word + w.get("punc", "")
        prev = word
    return text


def _split_balanced(words: list[dict], max_width: float, glossary: dict) -> list[list[dict]]:
    """Split one clause into the fewest near-equal pieces that fit, so no piece is a one-character orphan."""
    width = _width(apply_glossary(_join_words(words), glossary))
    n = max(1, int(np.ceil(width / max_width)))
    if n == 1:
        return [words]
    target = width / n
    pieces, cur = [], []
    for w in words:
        cur.append(w)
        if len(pieces) < n - 1 and _width(apply_glossary(_join_words(cur), glossary)) >= target:
            pieces.append(cur)
            cur = []
    if cur:
        pieces.append(cur)
    return pieces


def build_cues(words: list[dict], max_width: float = 22.0, min_duration_s: float = 0.8, glossary: dict | None = None) -> list[dict]:
    """Cues never cross a sentence end; clauses are packed up to max_width; a clause longer than that is
    split into near-equal pieces instead of being filled greedily (which strands a single character)."""
    glossary = glossary or {}
    sentences: list[list[list[dict]]] = []
    sentence: list[list[dict]] = []
    clause: list[dict] = []
    for w in words:
        if not w["text"].strip():
            continue
        clause.append(w)
        punc = w.get("punc", "")
        if any(ch in SENTENCE_END for ch in punc):
            sentence.append(clause)
            sentences.append(sentence)
            sentence, clause = [], []
        elif any(ch in CLAUSE_END for ch in punc):
            sentence.append(clause)
            clause = []
    if clause:
        sentence.append(clause)
    if sentence:
        sentences.append(sentence)

    groups: list[list[dict]] = []
    for sent in sentences:
        cur: list[dict] = []
        for cl in sent:
            for piece in _split_balanced(cl, max_width, glossary):
                if cur and _width(apply_glossary(_join_words(cur + piece), glossary)) > max_width:
                    groups.append(cur)
                    cur = []
                cur = cur + piece
        if cur:
            groups.append(cur)

    cues = []
    for g in groups:
        shown = apply_glossary(_join_words(g), glossary).strip().rstrip(TRAILING_DROP).strip()
        if shown:
            cues.append({"start": g[0]["start"], "end": g[-1]["end"], "text": shown})

    # Cues that start together would get zero length; merge each into the one that follows.
    merged: list[dict] = []
    for c in cues:
        if merged and c["start"] - merged[-1]["start"] < 0.05:
            merged[-1] = {"start": merged[-1]["start"], "end": max(merged[-1]["end"], c["end"]),
                          "text": merged[-1]["text"] + (" " if _needs_space(merged[-1]["text"], c["text"]) else "") + c["text"]}
        else:
            merged.append(c)
    cues = merged

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
