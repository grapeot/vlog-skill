"""Render an edit plan: drop cut regions from a recording and re-pace the remaining speech.

The pacing defaults below are the values a speaker approved after listening. Natural pauses are
kept as recorded; only stalls longer than the keep thresholds are shortened, and every inserted
pause is room tone from the same recording, never digital silence.
"""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path

import numpy as np

from .audio import encode_m4a, load_audio, measure_loudness, write_wav
from .transcribe import load_transcript, punc_kind

PLAN_SCHEMA = "vlog.edit_plan/1"
MANIFEST_SCHEMA = "vlog.manifest/1"

DEFAULT_PACING = {
    # A gap shorter than this (by the punctuation that precedes it) stays untouched inside an island.
    "keep_gap_s": {"period": 1.00, "comma": 0.75, "none": 0.60},
    # Pause before an island that starts a section listed in section_starts.
    "section_pause_s": 1.15,
    "section_match_window_s": 1.2,
    # Pause across a removed stutter or filler ("micro" cut).
    "after_micro_cut_s": {"period": 0.85, "comma": 0.55, "none": 0.08},
    # Pause across a removed retake, false start or passage ("major" cut).
    "after_major_cut_s": {"period": 0.88, "comma": 0.58, "none": 0.45},
    # A stall longer than keep_gap_s: [target, target_if_very_long, very_long_threshold].
    "long_gap_s": {"period": [0.85, 0.95, 1.60], "comma": [0.58, 0.66, 1.30], "none": [0.40, 0.50, 1.10]},
    "tail_s": 0.80,
    # Quiet margin already included at island edges by the edge refinement.
    "edge_quiet_margin_s": 0.06,
}

DEFAULT_EDGES = {
    "pre_pad_s": 0.045,
    "post_pad_s": 0.075,
    "max_onset_extension_s": 0.105,
    "max_release_extension_s": 0.165,
    "energy_threshold_mean_sq": 2.5e-5,  # about -46 dBFS
    "energy_window_s": 0.015,
    # A cut edge whose 15 ms level is at or above this is reported as inside speech.
    "warn_edge_db": -35.0,
}


def _merge(base: dict, override: dict | None) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load_plan(path: str | Path) -> dict:
    path = Path(path)
    plan = json.loads(path.read_text(encoding="utf-8"))
    base = path.parent
    for key in ("source_audio", "transcript", "output_wav", "output_m4a", "manifest"):
        if key in plan and plan[key] and not Path(plan[key]).is_absolute():
            plan[key] = str((base / plan[key]).resolve())
    validate_plan(plan)
    return plan


def validate_plan(plan: dict) -> None:
    missing = [k for k in ("source_audio", "transcript", "output_wav", "manifest") if not plan.get(k)]
    if missing:
        raise ValueError(f"edit plan is missing {', '.join(missing)}")
    for i, c in enumerate(plan.get("cuts", [])):
        if not (float(c["start"]) < float(c["end"])):
            raise ValueError(f"cut {i} has start >= end: {c}")
        if c.get("kind", "major") not in ("major", "micro"):
            raise ValueError(f"cut {i} kind must be 'major' or 'micro': {c}")


def find_room_tone(mono: np.ndarray, sr: int, length_s: float = 2.0, search_s: float = 600.0) -> tuple[float, float]:
    """The quietest window of length_s in the first search_s seconds, by mean energy."""
    hop = int(0.1 * sr)
    limit = min(len(mono), int(search_s * sr))
    n = limit // hop
    if n * hop < int(length_s * sr):
        return 0.0, min(length_s, len(mono) / sr)
    energy = (mono[: n * hop].reshape(n, hop).astype(np.float64) ** 2).mean(axis=1)
    k = int(length_s / 0.1)
    sums = np.convolve(energy, np.ones(k), mode="valid")
    i = int(np.argmin(sums))
    return i * 0.1, i * 0.1 + length_s


def _refine_edges(mono_sq, sr, t0, t1, min_bound, max_bound, edges) -> tuple[float, float]:
    """Pad an island so consonant onsets and releases survive, without crossing min/max bounds."""
    s0 = max(min_bound, t0 - edges["pre_pad_s"])
    s1 = min(max_bound, t1 + edges["post_pad_s"])
    win = max(1, int(edges["energy_window_s"] * sr))
    thr = edges["energy_threshold_mean_sq"]

    limit = int(min(max_bound, t1 + edges["max_release_extension_s"]) * sr)
    cur = int(s1 * sr)
    while cur + win < limit and float(np.mean(mono_sq[cur : cur + win])) >= thr:
        cur += win // 2
    s1 = min(cur / sr, max_bound)

    limit0 = int(max(min_bound, t0 - edges["max_onset_extension_s"]) * sr)
    cur0 = int(s0 * sr)
    while cur0 - win > limit0 and float(np.mean(mono_sq[cur0 - win : cur0])) >= thr:
        cur0 -= win // 2
    s0 = max(cur0 / sr, min_bound)
    return round(s0, 4), round(s1, 4)


def _append_crossfade(pieces: list[np.ndarray], clip: np.ndarray, fade: int) -> int:
    """Append clip, overlapping the previous piece by `fade` samples when both are long enough.

    Returns the overlap actually applied, so callers can keep exact sample positions.
    """
    if not pieces or len(pieces[-1]) <= fade or len(clip) <= fade:
        pieces.append(clip)
        return 0
    t = np.linspace(0.0, math.pi / 2.0, fade, dtype=np.float32)
    if clip.ndim == 2:
        t = t[:, None]
    prev = pieces[-1]
    overlap = prev[-fade:] * np.cos(t) + clip[:fade] * np.sin(t)
    pieces[-1] = prev[:-fade]
    pieces.append(overlap)
    pieces.append(clip[fade:])
    return fade


def _room_tone_clip(room: np.ndarray, n: int, seed: int) -> np.ndarray:
    if len(room) <= n + 1:  # tile a short room-tone window
        reps = n // max(1, len(room)) + 2
        room = np.concatenate([room] * reps, axis=0)
    offset = (seed * 7919) % max(1, len(room) - n - 1)
    return room[offset : offset + n].copy()


def _target_pause(pacing: dict, kind: str, cut_kinds: set[str], section_break: bool, raw_gap: float) -> float:
    if section_break:
        return pacing["section_pause_s"]
    if "major" in cut_kinds:
        return pacing["after_major_cut_s"][kind]
    if "micro" in cut_kinds:
        return pacing["after_micro_cut_s"][kind]
    short, long_, switch = pacing["long_gap_s"][kind]
    return long_ if raw_gap > switch else short


def render(plan: dict) -> dict:
    """Render the plan to WAV (and M4A if requested) and write the manifest. Returns the manifest."""
    sr = int(plan.get("sample_rate", 48000))
    pacing = _merge(DEFAULT_PACING, plan.get("pacing"))
    edges = _merge(DEFAULT_EDGES, plan.get("edges"))
    cuts = sorted(
        ({"start": float(c["start"]), "end": float(c["end"]), "kind": c.get("kind", "major"), "reason": c.get("reason", "")}
         for c in plan.get("cuts", [])),
        key=lambda c: c["start"],
    )
    section_starts = [float(s) for s in plan.get("section_starts", [])]

    audio = load_audio(plan["source_audio"], sr, 2)
    mono = audio.mean(axis=1)
    mono_sq = mono * mono
    total = len(audio) / sr

    rt = plan.get("room_tone", "auto")
    if rt == "auto" or rt is None:
        rt_start, rt_end = find_room_tone(mono, sr)
        room_source = "auto"
    else:
        rt_start, rt_end = float(rt["start"]), float(rt["end"])
        room_source = "plan"
    if not (0.0 <= rt_start < rt_end <= total + 1e-6) or rt_end - rt_start < 0.2:
        raise ValueError(f"room_tone window {rt_start}-{rt_end} s must lie inside the recording (0-{total:.2f} s) and be at least 0.2 s long")
    room = audio[int(rt_start * sr) : int(rt_end * sr)].copy()

    words = load_transcript(plan["transcript"])["words"]

    # A cut edge inside speech energy clips a kept syllable or leaves part of a deleted one.
    win = max(1, int(edges["energy_window_s"] * sr))
    warnings = []
    for idx, c in enumerate(cuts):
        for edge in ("start", "end"):
            centre = int(c[edge] * sr)
            seg = mono_sq[max(0, centre - win // 2): centre + win // 2]
            level = 10 * math.log10(float(seg.mean()) + 1e-12) if len(seg) else -120.0
            if level >= edges["warn_edge_db"]:
                warnings.append({"type": "cut_edge_in_speech", "cut_index": idx, "edge": edge, "time": c[edge],
                                 "level_db": round(level, 1),
                                 "reason": c["reason"], "hint": "move this edge into a quiet run from `vlog quiet`"})

    def in_cut(t0: float, t1: float) -> bool:
        mid = 0.5 * (t0 + t1)
        return any(c["start"] <= mid <= c["end"] for c in cuts)

    kept = []
    for w in words:
        t0, t1 = float(w["start"]), float(w["end"])
        if in_cut(t0, t1):
            continue
        if t1 - t0 < 0.04:  # aligners emit zero-length tokens; give them a little audio
            t1 = min(total, t0 + 0.05)
        kept.append({"text": w["text"], "punc": w.get("punc", ""), "start": t0, "end": t1})
    if not kept:
        raise ValueError("every word falls inside a cut; nothing to render")

    groups: list[list[dict]] = [[kept[0]]]
    for tok in kept[1:]:
        prev = groups[-1][-1]
        cut_between = any(c["start"] >= prev["start"] - 0.05 and c["end"] <= tok["end"] + 0.05 for c in cuts)
        if cut_between or tok["start"] - prev["end"] > pacing["keep_gap_s"][punc_kind(prev["punc"])]:
            groups.append([tok])
        else:
            groups[-1].append(tok)

    def mid(w: dict) -> float:
        return 0.5 * (w["start"] + w["end"])

    islands = []
    dropped = []
    for i, g in enumerate(groups):
        t0, t1 = g[0]["start"], g[-1]["end"]
        min_b = (groups[i - 1][-1]["end"] if i > 0 else 0.0) + 0.02
        max_b = (groups[i + 1][0]["start"] if i + 1 < len(groups) else total) - 0.02
        # Never let the island (or its edge padding) reach into deleted audio. A cut can start or
        # end inside a kept boundary word when the aligner stretched that word over a filler or a
        # repeated syllable, so compare against the boundary words' midpoints, not their edges.
        for c in cuts:
            if c["end"] <= t0 + 0.05 or c["end"] <= mid(g[0]):
                min_b = max(min_b, c["end"])
            if c["start"] >= t1 - 0.05 or c["start"] >= mid(g[-1]):
                max_b = min(max_b, c["start"])
        min_b, max_b = max(0.0, min_b), min(total, max_b)
        r0, r1 = _refine_edges(mono_sq, sr, max(t0, min_b), min(t1, max_b), min_b, max_b, edges)
        if r1 - r0 < 0.02:  # the cuts left nothing of this island
            dropped.append("".join(x["text"] for x in g))
            continue
        islands.append({"raw_start": r0, "raw_end": r1, "tokens": g})
    if not islands:
        raise ValueError("the cuts leave no audio to render")

    fade = int(float(plan.get("crossfade_ms", 25)) / 1000 * sr)
    lead = float(plan.get("lead_in_s", 0.40))
    pieces: list[np.ndarray] = [_room_tone_clip(room, int(lead * sr), 0)] if lead > 0 else []
    cur = len(pieces[0]) if pieces else 0
    out_islands, out_words = [], []

    for i, isl in enumerate(islands):
        clip = audio[int(isl["raw_start"] * sr) : int(isl["raw_end"] * sr)].copy()
        out_start = cur - _append_crossfade(pieces, clip, fade)
        cur = out_start + len(clip)
        offset = out_start / sr - isl["raw_start"]
        for tok in isl["tokens"]:
            out_words.append(
                {
                    "text": tok["text"],
                    "punc": tok["punc"],
                    "start": round(tok["start"] + offset, 4),
                    "end": round(tok["end"] + offset, 4),
                    "raw_start": round(tok["start"], 4),
                    "raw_end": round(tok["end"], 4),
                }
            )

        if i + 1 < len(islands):
            nxt = islands[i + 1]
            w_end = isl["tokens"][-1]["end"]
            w_next = nxt["tokens"][0]["start"]
            kind = punc_kind(isl["tokens"][-1]["punc"])
            section_break = any(abs(nxt["raw_start"] - s) < pacing["section_match_window_s"] for s in section_starts)
            last_mid, next_mid = mid(isl["tokens"][-1]), mid(nxt["tokens"][0])
            cut_kinds = {c["kind"] for c in cuts
                         if (c["start"] >= w_end - 0.15 and c["end"] <= w_next + 0.15)
                         or (c["start"] >= last_mid and c["end"] <= next_mid)}
            pause = _target_pause(pacing, kind, cut_kinds, section_break, w_next - w_end)
            extra = max(0.0, pause - pacing["edge_quiet_margin_s"])
            if extra > 0.015:
                pad = _room_tone_clip(room, int((extra + 2 * fade / sr) * sr), i)
                cur = cur - _append_crossfade(pieces, pad, fade) + len(pad)
        else:
            pause = pacing["tail_s"]
            n_tail = int((pause + fade / sr) * sr)
            pad = room[:n_tail].copy() if len(room) >= n_tail else _room_tone_clip(room, n_tail, 0)
            cur = cur - _append_crossfade(pieces, pad, fade) + len(pad)

        out_islands.append(
            {
                "index": i,
                "out_start": round(out_start / sr, 3),
                "out_end": round((out_start + len(clip)) / sr, 3),
                "raw_start": isl["raw_start"],
                "raw_end": isl["raw_end"],
                "pause_after": round(pause, 3),
                "word_raw_start": isl["tokens"][0]["start"],
                "word_raw_end": isl["tokens"][-1]["end"],
                "text": "".join(t["text"] for t in isl["tokens"]),
            }
        )

    out = np.concatenate(pieces, axis=0)
    duration = len(out) / sr
    assert len(out) == cur, (len(out), cur)  # sample bookkeeping must match the assembled audio
    peak = float(np.max(np.abs(out)))
    write_wav(plan["output_wav"], out, sr)
    if plan.get("output_m4a"):
        encode_m4a(plan["output_wav"], plan["output_m4a"])
    loudness = measure_loudness(plan["output_wav"])

    manifest = {
        "schema": MANIFEST_SCHEMA,
        "source_audio": plan["source_audio"],
        "transcript": plan["transcript"],
        "output_wav": plan["output_wav"],
        "output_m4a": plan.get("output_m4a"),
        "sample_rate": sr,
        "raw_duration_s": round(total, 3),
        "edited_duration_s": round(duration, 3),
        "peak_linear": round(peak, 4),
        "loudness": loudness,
        "room_tone": {"start": round(rt_start, 3), "end": round(rt_end, 3), "source": room_source},
        "pacing": pacing,
        "cuts": cuts,
        "islands": out_islands,
        "dropped_islands": dropped,
        "warnings": warnings,
        "words": out_words,
    }
    Path(plan["manifest"]).parent.mkdir(parents=True, exist_ok=True)
    Path(plan["manifest"]).write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest
