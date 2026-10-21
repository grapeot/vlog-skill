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


_GOOD_END = set("的了呢啊吧吗嘛呀么着过就是在和说")  # a CJK piece may end after these without cutting a word in two
_BAD_START = set("的了呢啊吧吗嘛呀么着过们")  # ... and should not start with these
_GOOD_START = ("然后", "但是", "所以", "因为", "如果", "而且", "那么", "我们", "你们", "他们", "这个", "那个", "就是",
               "其实", "可以", "还是", "或者", "比如", "只要", "不过", "而是")  # common clause openers


def _is_latin(text: str) -> bool:
    return any(ch.isascii() and ch.isalnum() for ch in text)


def _cut_penalty(words: list[dict], k: int) -> int:
    """Cost of cutting between words[k-1] and words[k]. CJK aligners emit one character per word, so a cut
    between two arbitrary characters can split a word ("机" | "器"); prefer cuts after a particle or at a
    change of script."""
    prev, nxt = words[k - 1]["text"].strip(), words[k]["text"].strip()
    if nxt[:1] in _BAD_START:
        return 3
    if "".join(w["text"].strip() for w in words[k:k + 2]).startswith(_GOOD_START):
        return 0
    if prev[-1:] in _GOOD_END or _is_latin(prev) != _is_latin(nxt) or (_is_latin(prev) and _is_latin(nxt)):
        return 0
    return 2


def _glossary_cuts(words: list[dict], glossary: dict) -> set[int]:
    """Cut positions that would fall inside a glossary key, which would put the raw ASR error on screen."""
    joined = _join_words(words)
    bounds = [len(_join_words(words[:k])) for k in range(len(words) + 1)]
    bad = set()
    for key in glossary:
        st = joined.find(key)
        while st >= 0:
            bad.update(k for k in range(1, len(words)) if st < bounds[k] < st + len(key))
            st = joined.find(key, st + 1)
    return bad


def _split_balanced(words: list[dict], max_width: float, glossary: dict) -> list[list[dict]]:
    """Split one clause into the fewest pieces that each fit max_width, choosing all cuts together: pieces
    stay near-equal (no one-character orphan), cuts prefer likely word boundaries, and no cut falls inside
    a glossary key."""
    m = len(words)
    cache: dict[tuple[int, int], float] = {}

    def width(a: int, b: int) -> float:
        if (a, b) not in cache:
            cache[(a, b)] = _width(apply_glossary(_join_words(words[a:b]), glossary))
        return cache[(a, b)]

    total = width(0, m)
    if total <= max_width or m < 2:
        return [words]
    bad = _glossary_cuts(words, glossary)
    penalty = [0] + [_cut_penalty(words, k) for k in range(1, m)] + [0]
    inf = float("inf")
    for n in range(max(2, int(np.ceil(total / max_width))), m + 1):
        target = total / n
        best = [[inf] * (m + 1) for _ in range(n + 1)]
        back = [[0] * (m + 1) for _ in range(n + 1)]
        best[0][0] = 0.0
        for j in range(1, n + 1):
            for k in ([m] if j == n else range(j, m)):
                if k in bad:
                    continue
                cost = 0.0 if k == m else abs(width(0, k) - target * j) + 1.5 * penalty[k]
                for a in range(k - 1, j - 2, -1):
                    if width(a, k) > max_width:
                        break
                    if best[j - 1][a] + cost < best[j][k]:
                        best[j][k], back[j][k] = best[j - 1][a] + cost, a
        if best[n][m] < inf:
            cuts, k = [], m
            for j in range(n, 0, -1):
                cuts.append(k)
                k = back[j][k]
            cuts = [0] + cuts[::-1]
            return [words[cuts[i]:cuts[i + 1]] for i in range(n)]
    return [[w] for w in words]  # a single word wider than max_width


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
