"""Split a word-level transcript into utterances at pauses, for reading and for choosing cuts."""

from __future__ import annotations


def split_utterances(words: list[dict], min_gap_s: float = 0.35) -> list[dict]:
    utterances: list[dict] = []
    current: list[dict] = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        gap = (nxt["start"] - w["end"]) if nxt else None
        if nxt is None or gap > min_gap_s:
            utterances.append(
                {
                    "index": len(utterances),
                    "start": round(current[0]["start"], 2),
                    "end": round(current[-1]["end"], 2),
                    "text": "".join(x["text"] + x.get("punc", "") for x in current),
                    "gap_after": round(gap, 2) if gap is not None else None,
                }
            )
            current = []
    return utterances


def _clock(t: float) -> str:
    return f"{int(t // 60):02d}:{t % 60:05.2f}"


def format_table(utterances: list[dict], long_gap_s: float = 0.8) -> str:
    """One line per utterance; gaps at or above long_gap_s are bracketed so stalls stand out."""
    lines = []
    for u in utterances:
        gap = u["gap_after"]
        tail = "" if gap is None else (f"  [gap {gap:.2f}s]" if gap >= long_gap_s else f"  (gap {gap:.2f}s)")
        lines.append(
            f"{u['index']:03d} | {_clock(u['start'])} - {_clock(u['end'])} "
            f"({u['start']:8.2f}s - {u['end']:8.2f}s) | {u['text']}{tail}"
        )
    return "\n".join(lines) + "\n"
