"""Regression tests for issues found in the first independent code review."""

import json

import numpy as np
import pytest

from synth import SR, dominant_freq, transcript, write_project
from vlog_skill import cli
from vlog_skill.audio import load_audio
from vlog_skill.edit import load_plan, render
from vlog_skill.subtitles import build_cues
from vlog_skill.verify import verify


def test_cut_inside_a_stretched_boundary_word_is_honoured(tmp_path):
    # The aligner stretched X over a doubled syllable D (real D audio 1.28-1.40); the cut sits on measured quiet.
    words = [("X", 1.00, 1.42, 300, ""), ("Y", 1.60, 1.80, 500, "。")]
    plan = load_plan(write_project(tmp_path, words, 3.0, [{"start": 1.24, "end": 1.45, "kind": "micro", "reason": "doubled"}]))
    # put the doubled syllable's real audio inside the cut
    audio = load_audio(tmp_path / "raw.wav", SR, 2)
    t = np.arange(int(0.12 * SR)) / SR
    audio = audio.copy()
    audio[int(1.28 * SR): int(1.28 * SR) + len(t)] = (0.3 * np.sin(2 * np.pi * 900 * t))[:, None]
    audio[int(1.24 * SR): int(1.28 * SR)] = 0.0  # quiet just before D
    from vlog_skill.audio import write_wav

    write_wav(tmp_path / "raw.wav", audio, SR)
    m = render(plan)
    assert m["islands"][0]["raw_end"] <= 1.24 + 1e-6
    assert m["islands"][0]["pause_after"] == 0.08  # micro-cut pause, not a long-gap pause
    out = load_audio(tmp_path / "out" / "edited.wav", SR, 1)
    spec_has_900 = any(abs(dominant_freq(out[i:i + 2400]) - 900) < 20 for i in range(0, len(out) - 2400, 1200))
    assert not spec_has_900
    rep = verify(m, transcript(words)["words"], {"words": [], "text": ""})
    assert rep["joins_checked"] == 1


def test_verify_window_covers_start_of_next_island_after_section_pause(tmp_path):
    words = [("我", 1.0, 1.2, 300, "。"), ("错", 2.0, 2.2, 400, ""), ("好", 3.5, 3.7, 500, "。")]
    plan = load_plan(write_project(tmp_path, words, 5.0, [{"start": 1.9, "end": 2.6, "kind": "major", "reason": "retake"}],
                                   section_starts=[3.45]))
    m = render(plan)
    k = m["islands"][1]["out_start"]
    assert k - m["islands"][0]["out_end"] > 1.0  # section pause wider than the old window
    edited = {"words": [{"text": "我", "start": 0.4, "end": 0.6}, {"text": "呃", "start": k + 0.02, "end": k + 0.1},
                        {"text": "好", "start": k + 0.2, "end": k + 0.4}], "text": "我呃好"}
    rep = verify(m, transcript(words)["words"], edited)
    assert rep["joins_flagged"] == 1


def test_latin_fillers_and_case_insensitive_phrases(tmp_path):
    words = [("so", 1.0, 1.2, 300, ""), ("bad", 2.0, 2.2, 400, ""), ("we", 3.0, 3.2, 500, ".")]
    m = render(load_plan(write_project(tmp_path, words, 4.0, [{"start": 1.9, "end": 2.4, "kind": "major", "reason": "x"}])))
    j = m["islands"][0]["out_end"]
    edited = {"words": [{"text": "so", "start": j - 0.3, "end": j - 0.1}, {"text": "um", "start": j + 0.1, "end": j + 0.2},
                        {"text": "we", "start": j + 0.5, "end": j + 0.7}], "text": "So, um, we. Let me redo that."}
    rep = verify(m, transcript(words)["words"], edited, expect_absent=["let me redo that"])
    assert {i["detail"] for i in rep["joins"][0]["issues"]} == {"um"}
    assert rep["expect_absent_hits"]


def test_invalid_room_tone_is_rejected(tmp_path):
    words = [("我", 1.0, 1.2, 300, "。")]
    with pytest.raises(ValueError):
        render(load_plan(write_project(tmp_path, words, 2.0, [], room_tone={"start": 20, "end": 22})))


def test_no_lead_in_keeps_word_times_exact(tmp_path):
    words = [("我", 0.5, 0.7, 300, "，"), ("好", 1.0, 1.2, 600, "。")]
    m = render(load_plan(write_project(tmp_path, words, 2.0, [], lead_in_s=0, room_tone={"start": 1.5, "end": 2.0})))
    assert m["islands"][0]["out_start"] >= 0
    out = load_audio(tmp_path / "out" / "edited.wav", SR, 1)
    w = m["words"][0]
    onset = np.argmax(np.abs(out) > 0.05) / SR
    assert abs(onset - w["start"]) < 0.015


def test_subtitle_latin_spacing_and_no_overlap():
    ws = [{"text": x, "start": i * 0.3, "end": i * 0.3 + 0.25, "punc": p}
          for i, (x, p) in enumerate([("Well", ","), ("so", ""), ("plan", ","), ("and", ""), ("ship", ".")])]
    assert build_cues(ws)[0]["text"] == "Well, so plan, and ship."
    close = [{"text": "甲", "start": 1.00, "end": 1.01, "punc": "。"}, {"text": "乙", "start": 1.02, "end": 1.03, "punc": "。"}]
    cues = build_cues(close)  # starting together: merged instead of a zero-length cue
    assert len(cues) == 1 and cues[0]["text"] == "甲乙" and cues[0]["end"] > cues[0]["start"]
    apart = [{"text": "甲", "start": 1.00, "end": 1.01, "punc": "。"}, {"text": "乙", "start": 1.10, "end": 1.20, "punc": "。"}]
    cues = build_cues(apart)
    assert len(cues) == 2 and cues[0]["end"] <= cues[1]["start"]


def test_usage_error_is_json(capsys):
    assert cli.main(["quiet", "a.wav"]) == cli.EXIT_USAGE
    env = json.loads(capsys.readouterr().out)
    assert env["ok"] is False and env["error"]["type"] == "UsageError"


def test_missing_media_is_bad_input(capsys, tmp_path):
    assert cli.main(["quiet", str(tmp_path / "nope.wav"), "--start", "0", "--end", "1"]) == cli.EXIT_INPUT
    assert json.loads(capsys.readouterr().out)["error"]["type"] == "FileNotFoundError"


def test_init_refuses_inside_the_repository(capsys):
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    assert cli.main(["init", str(repo / "projects" / "demo")]) == cli.EXIT_INPUT
    assert "inside the vlog-skill repository" in json.loads(capsys.readouterr().out)["error"]["message"]
    assert not (repo / "projects").exists()


def test_second_review_lows():
    from vlog_skill.verify import _find_phrase

    assert _find_phrase("C++", "We can call a function here.") == []
    assert _find_phrase("C++", "we use c++ here") == [7]
    same = [{"text": "好", "start": 1.0, "end": 1.1, "punc": "。"}, {"text": "的", "start": 1.0, "end": 1.2, "punc": "。"}]
    cues = build_cues(same)
    assert len(cues) == 1 and cues[0]["end"] > cues[0]["start"]
