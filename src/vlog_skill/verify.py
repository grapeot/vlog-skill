"""Check an edit by comparing the raw transcript with a fresh transcript of the edited audio.

Forced-aligner timestamps are least reliable exactly where cuts happen (fillers get squeezed, one
syllable's audio gets attributed to its neighbour), so a cut that looks right on token times can
leave a filler or a repeated syllable in the audio. The only dependable check is to transcribe the
edited audio again and look at every join.
"""

from __future__ import annotations

import re

SCHEMA = "vlog.verify/1"
DEFAULT_FILLERS = ["呃", "嗯", "um", "uh", "erm"]
CJK = re.compile(r"[一-鿿]")


def _join_words(words: list[dict]) -> str:
    """Concatenate CJK tokens directly and put a space between Latin tokens."""
    out = ""
    for w in words:
        tok = w["text"].strip()
        if not tok:
            continue
        if out and out[-1].isascii() and out[-1].isalnum() and tok[0].isascii() and tok[0].isalnum():
            out += " "
        out += tok
    return out


def _text_between(words: list[dict], t0: float, t1: float) -> str:
    return _join_words([w for w in words if t0 <= w["start"] < t1])


def _normalize(text: str) -> str:
    """Lower-case, punctuation to single spaces; CJK characters are kept as they are."""
    return re.sub(r"[^\w\u4e00-\u9fff]+", " ", text.lower()).strip()


def _find_phrase(phrase: str, text: str) -> list[int]:
    """Positions of phrase in text, ignoring case, punctuation and spacing differences."""
    p, s = _normalize(phrase), _normalize(text)
    if len(p.replace(" ", "")) < len(re.sub(r"\s", "", phrase)) * 0.5 or not p:
        # mostly symbols (for example "C++"): normalising would change its meaning, search it as written
        return [m.start() for m in re.finditer(re.escape(phrase.lower()), text.lower())]
    hits = [m.start() for m in re.finditer(re.escape(p), s)]
    if not hits:  # CJK text from an aligner has no spaces; also try with spaces removed
        p2, s2 = p.replace(" ", ""), s.replace(" ", "")
        hits = [m.start() for m in re.finditer(re.escape(p2), s2)] if p2 else []
    return hits


def _doubled(text: str) -> list[str]:
    return [m.group(0) for m in re.finditer(r"([一-鿿])\1", text)]


def _contains_filler(text: str, fillers: list[str]) -> list[str]:
    found = []
    for f in fillers:
        if CJK.search(f):
            if f in text:
                found.append(f)
        elif re.search(rf"(?<![A-Za-z]){re.escape(f)}(?![A-Za-z])", text, flags=re.IGNORECASE):
            found.append(f)
    return found


def verify(
    manifest: dict,
    raw_words: list[dict],
    edited: dict,
    expect_absent: list[str] | None = None,
    fillers: list[str] | None = None,
    window_s: float = 2.2,
    near_s: float = 1.0,
    allow_doubles: list[str] | None = None,
) -> dict:
    """Return a vlog.verify/1 report. `clean` is true only when nothing needs a human look."""
    fillers = DEFAULT_FILLERS if fillers is None else fillers
    allow = set(allow_doubles or [])
    ed_words = edited["words"]
    cuts = manifest.get("cuts") or manifest.get("exclusions", [])  # "exclusions": pre-schema manifests
    islands = manifest["islands"]

    joins = []
    for p, q in zip(islands, islands[1:]):
        # Decide joins on word times: a cut can end inside the refined edge of an island.
        p_end = p.get("word_raw_end", p["raw_end"])
        q_start = q.get("word_raw_start", q["raw_start"])
        crossed = [c for c in cuts if c["start"] < q_start and c["end"] > p_end]
        if not crossed:
            continue
        j, k = p["out_end"], q["out_start"]
        edited_ctx = _text_between(ed_words, j - window_s, k + window_s)
        near = _text_between(ed_words, j - near_s, k + near_s)
        raw_before = _text_between(raw_words, p["raw_end"] - window_s, p["raw_end"] + 0.05)
        raw_after = _text_between(raw_words, q["raw_start"] - 0.05, q["raw_start"] + window_s)
        issues = []
        for f in _contains_filler(near, fillers):
            issues.append({"type": "filler_near_join", "detail": f})
        for d in _doubled(near):
            if d not in allow:
                issues.append({"type": "doubled_near_join", "detail": d})
        joins.append(
            {
                "out_time": round(j, 3),
                "raw_gap": [p["raw_end"], q["raw_start"]],
                "cut_reasons": [c.get("reason", "") for c in crossed],
                "edited": edited_ctx,
                "raw_before": raw_before,
                "raw_after": raw_after,
                "issues": issues,
                "status": "review" if issues else "ok",
            }
        )

    full = edited.get("text") or _join_words(ed_words)
    absent_hits = []
    norm_full = _normalize(full)
    for phrase in expect_absent or []:
        for pos in _find_phrase(phrase, full):
            absent_hits.append({"phrase": phrase, "context": norm_full[max(0, pos - 15): pos + len(phrase) + 15]})

    flagged = [j for j in joins if j["status"] != "ok"]
    return {
        "schema": SCHEMA,
        "edited_media": edited.get("media"),
        "edited_duration_s": manifest.get("edited_duration_s"),
        "joins_checked": len(joins),
        "joins_flagged": len(flagged),
        "expect_absent_hits": absent_hits,
        "clean": not flagged and not absent_hits,
        "joins": joins,
    }


def _clock(t: float) -> str:
    t = round(t, 2)
    return f"{int(t // 60)}:{t % 60:05.2f}"


def to_markdown(report: dict) -> str:
    lines = [
        "# Edit verification",
        "",
        f"- Edited duration: {report.get('edited_duration_s')} s",
        f"- Joins checked: {report['joins_checked']}, flagged: {report['joins_flagged']}",
        f"- Expected-absent phrases found: {len(report['expect_absent_hits'])}",
        f"- Clean: {'yes' if report['clean'] else 'no'}",
        "",
    ]
    if report["expect_absent_hits"]:
        lines += ["## Phrases that should be gone", ""]
        lines += [f"- `{h['phrase']}`: ...{h['context']}..." for h in report["expect_absent_hits"]]
        lines.append("")
    lines += ["## Joins", "", "| Time | Status | Edited text around the join | Raw before / after | Cut |", "|---|---|---|---|---|"]
    for j in report["joins"]:
        status = j["status"] if not j["issues"] else j["status"] + ": " + ", ".join(f"{i['type']} {i['detail']}" for i in j["issues"])
        lines.append(
            f"| {_clock(j['out_time'])} | {status} | {j['edited']} | {j['raw_before']} ‖ {j['raw_after']} | {'; '.join(j['cut_reasons'])[:60]} |"
        )
    return "\n".join(lines) + "\n"
