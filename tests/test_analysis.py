import json

import numpy as np

from synth import SR, make_recording, transcript, write_project
from vlog_skill.audio import rms_db, write_wav
from vlog_skill.edit import load_plan, render
from vlog_skill.quiet import find_quiet_runs, quiet_runs_from_envelope
from vlog_skill.subtitles import build_cues, to_srt
from vlog_skill.transcribe import attach_punctuation, normalize, punc_kind
from vlog_skill.utterances import format_table, split_utterances
from vlog_skill.verify import verify

WORDS = [("你", 1.0, 1.2, 300, ""), ("好", 1.3, 1.5, 400, "。"), ("再", 2.5, 2.7, 500, ""), ("见", 2.75, 2.95, 600, "。")]


def test_quiet_runs_find_the_gaps(tmp_path):
    write_wav(tmp_path / "a.wav", make_recording(WORDS, 3.5), SR)
    res = find_quiet_runs(tmp_path / "a.wav", 0.9, 2.6)
    runs = res["runs"]
    # the 0.1 s gap between 你 and 好, and the 1.0 s gap before 再
    assert any(1.19 <= r["start"] <= 1.23 and 1.27 <= r["end"] <= 1.32 for r in runs), runs
    assert any(r["duration"] > 0.9 for r in runs)
    assert all(r["min_db"] < -40 for r in runs)


def test_quiet_runs_envelope_closes_trailing_run():
    db = np.array([-20, -50, -50, -50, -20, -55, -55, -55, -55], dtype=np.float32)
    runs = quiet_runs_from_envelope(db, 10.0, -40, 0.03)
    assert [(r["start"], r["end"]) for r in runs] == [(10.01, 10.04), (10.05, 10.09)]


def test_rms_db_levels():
    tone = 0.5 * np.sin(2 * np.pi * 440 * np.arange(SR) / SR)
    assert abs(float(rms_db(tone, SR).mean()) - 20 * np.log10(0.5 / np.sqrt(2))) < 0.2


def test_punctuation_attached_from_text():
    words = [{"text": "我", "start": 0, "end": 1}, {"text": "们", "start": 1, "end": 2}, {"text": "PR", "start": 2, "end": 3}]
    attach_punctuation(words, "我，们说PR。")
    assert [w["punc"] for w in words] == ["，", "", "。"]
    assert punc_kind("，") == "comma" and punc_kind("。") == "period" and punc_kind("") == "none"


def test_normalize_accepts_engine_dump():
    raw = {"segments": [{"text": "好", "start": 0.1, "end": 0.3}, {"text": " ", "start": 0.3, "end": 0.3}],
           "chunks": [{"text": "好。"}], "language": "Chinese"}
    doc = normalize(raw, media="x.wav")
    assert doc["schema"] == "vlog.transcript/1" and doc["words"] == [{"text": "好", "start": 0.1, "end": 0.3, "punc": "。"}]


def test_utterances_split_at_pauses():
    utts = split_utterances(transcript(WORDS)["words"], 0.35)
    assert [u["text"] for u in utts] == ["你好。", "再见。"]
    assert "[gap 1.00s]" in format_table(utts)


def _verify_case(tmp_path, edited_words):
    words = [("那", 1.0, 1.2, 300, ""), ("要", 2.0, 2.2, 400, ""), ("要", 2.3, 2.5, 500, ""), ("好", 2.6, 2.8, 600, "。")]
    plan = load_plan(write_project(tmp_path, words, 4.0, [{"start": 1.3, "end": 1.9, "kind": "major", "reason": "retake"}]))
    manifest = render(plan)
    edited = {"words": [{"text": t, "start": s, "end": s + 0.2} for t, s in edited_words], "text": "".join(t for t, _ in edited_words)}
    return manifest, transcript(words)["words"], edited


def test_verify_flags_doubles_and_fillers_near_joins(tmp_path):
    manifest, raw_words, _ = _verify_case(tmp_path, [])
    j = manifest["islands"][0]["out_end"]
    edited = {"words": [{"text": "那", "start": j - 0.3, "end": j - 0.1}, {"text": "呃", "start": j + 0.05, "end": j + 0.1},
                        {"text": "要", "start": j + 0.2, "end": j + 0.4}, {"text": "要", "start": j + 0.5, "end": j + 0.7}],
              "text": "那呃要要"}
    rep = verify(manifest, raw_words, edited, expect_absent=["错误"])
    assert rep["joins_checked"] == 1 and rep["joins_flagged"] == 1 and not rep["clean"]
    types = {i["type"] for i in rep["joins"][0]["issues"]}
    assert types == {"filler_near_join", "doubled_near_join"}
    assert verify(manifest, raw_words, edited, allow_doubles=["要要"], fillers=[])["clean"]


def test_verify_reports_expected_absent_phrase(tmp_path):
    manifest, raw_words, _ = _verify_case(tmp_path, [])
    edited = {"words": [{"text": "那", "start": 0.4, "end": 0.6}], "text": "那我们下次再说吧"}
    rep = verify(manifest, raw_words, edited, expect_absent=["下次再说"])
    assert not rep["clean"] and rep["expect_absent_hits"][0]["phrase"] == "下次再说"


def test_subtitles_chunking_and_glossary():
    text = "这个P二今天合并，我们先看一下测试结果，再决定要不要把第二个模块也一起改掉，最后留一点时间给大家提问。下一句。"
    words, t = [], 0.0
    for ch in text:
        if ch in "，。":
            words[-1]["punc"] = ch
            continue
        words.append({"text": ch, "start": t, "end": t + 0.2, "punc": ""})
        t += 0.25
    cues = build_cues(words, 22, glossary={"P二": "PR"})
    assert cues[0]["text"].startswith("这个PR今天合并")
    assert all(not c["text"].endswith(("，", "。")) for c in cues)
    assert cues[-1]["text"] == "下一句"  # never merged across a sentence end
    srt = to_srt(cues)
    assert srt.startswith("1\n00:00:00,000 --> ") and ",1000" not in srt
