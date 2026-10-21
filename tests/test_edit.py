import json

import numpy as np
import pytest

from synth import SR, dominant_freq, write_project
from vlog_skill.audio import load_audio
from vlog_skill.edit import DEFAULT_PACING, find_room_tone, load_plan, render

# text, start, end, freq, punc. One clause, a stall, a retake to cut, a doubled syllable, a sentence end.
WORDS = [
    ("我", 1.00, 1.20, 300, ""),
    ("们", 1.25, 1.45, 400, "，"),
    ("看", 1.80, 2.00, 500, ""),      # comma gap 0.35 s: natural, stays untouched
    ("那", 2.05, 2.25, 600, ""),
    ("错", 4.00, 4.20, 700, ""),      # retake: cut 3.0-4.6
    ("要", 5.00, 5.20, 800, ""),
    ("要", 5.30, 5.50, 900, ""),      # doubled: cut the second one
    ("好", 5.60, 5.80, 1000, "。"),
    ("完", 8.00, 8.20, 1100, "。"),   # long stall after a period: shortened
]
CUTS = [
    {"start": 3.0, "end": 4.6, "kind": "major", "reason": "retake"},
    {"start": 5.25, "end": 5.55, "kind": "micro", "reason": "doubled syllable"},
]


@pytest.fixture()
def rendered(tmp_path):
    plan = load_plan(write_project(tmp_path, WORDS, 10.0, CUTS))
    return render(plan), tmp_path


def test_cut_words_are_gone_and_kept_words_present(rendered):
    manifest, tmp = rendered
    kept = "".join(w["text"] for w in manifest["words"])
    assert kept == "我们看那要好完"
    audio = load_audio(tmp / "out" / "edited.wav", SR, 1)
    for w in manifest["words"]:
        seg = audio[int((w["start"] + 0.05) * SR): int((w["end"] - 0.05) * SR)]
        expected = {x[0] + str(x[1]): x[3] for x in WORDS}[w["text"] + str(w["raw_start"])]
        assert abs(dominant_freq(seg) - expected) < 15, (w, dominant_freq(seg))


def test_natural_pause_kept_and_stall_shortened(rendered):
    manifest, _ = rendered
    by_text = {}
    for w in manifest["words"]:
        by_text.setdefault(w["text"], w)
    # 们 -> 看 was a 0.35 s comma pause: untouched (same island, same offset)
    gap = by_text["看"]["start"] - by_text["们"]["end"]
    assert abs(gap - 0.35) < 1e-3
    # 好 -> 完 was a 2.2 s stall after a period: shortened to about the long-gap target
    words = manifest["words"]
    stall = words[-1]["start"] - words[-2]["end"]
    assert 0.8 < stall < 1.3


def test_manifest_maps_output_back_to_raw(rendered):
    manifest, _ = rendered
    assert manifest["schema"] == "vlog.manifest/1"
    for isl in manifest["islands"]:
        assert isl["raw_end"] > isl["raw_start"] and isl["out_end"] > isl["out_start"]
        assert abs((isl["out_end"] - isl["out_start"]) - (isl["raw_end"] - isl["raw_start"])) < 0.002
    assert manifest["edited_duration_s"] < manifest["raw_duration_s"]
    assert manifest["loudness"]["integrated_lufs"] is not None


def test_edges_never_reach_into_a_cut(rendered):
    manifest, _ = rendered
    for isl in manifest["islands"]:
        for c in manifest["cuts"]:
            overlap = min(isl["raw_end"], c["end"]) - max(isl["raw_start"], c["start"])
            assert overlap <= 1e-6, (isl, c)


def test_pacing_override_merges_with_defaults(tmp_path):
    plan = load_plan(write_project(tmp_path, WORDS, 10.0, CUTS, pacing={"long_gap_s": {"period": [0.3, 0.3, 9.0]}}))
    m = render(plan)
    assert m["pacing"]["keep_gap_s"] == DEFAULT_PACING["keep_gap_s"]
    stall = m["words"][-1]["start"] - m["words"][-2]["end"]
    assert stall < 0.6


def test_invalid_cut_rejected(tmp_path):
    with pytest.raises(ValueError):
        load_plan(write_project(tmp_path, WORDS, 10.0, [{"start": 5, "end": 4}]))


def test_auto_room_tone_finds_quiet_window():
    from synth import make_recording

    x = make_recording(WORDS, 10.0)[:, 0]
    start, end = find_room_tone(x, SR, 1.5)
    for _, ws, we, _, _ in WORDS:
        assert we <= start or ws >= end
