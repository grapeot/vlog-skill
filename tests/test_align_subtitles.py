import json

import numpy as np
import pytest

from synth import SR, make_recording
from vlog_skill import cli
from vlog_skill.align import anchors, offsets
from vlog_skill.audio import write_wav
from vlog_skill.subtitles import build_cues

WORDS = [(c, 1.0 + i * 0.3, 1.2 + i * 0.3, 200 + 37 * i, "") for i, c in enumerate("我们先看一下这个问题")]


def test_offsets_detect_a_shift(tmp_path):
    rec = make_recording(WORDS, 6.0)
    write_wav(tmp_path / "a.wav", rec, SR)
    shift = int(0.12 * SR)
    write_wav(tmp_path / "b.wav", np.concatenate([np.zeros((shift, 2), np.float32), rec])[: len(rec)], SR)
    write_wav(tmp_path / "c.wav", rec, SR)
    same = offsets(str(tmp_path / "a.wav"), str(tmp_path / "c.wav"), [0.5], window=5)
    late = offsets(str(tmp_path / "a.wav"), str(tmp_path / "b.wav"), [0.5], window=5)
    assert same["aligned"] and abs(same["points"][0]["offset_ms"]) < 1
    assert not late["aligned"] and abs(late["points"][0]["offset_ms"] - 120) < 2


def test_anchors_resolve_phrases_and_fail_loudly():
    words = [{"text": c, "start": float(i), "end": i + 0.5} for i, c in enumerate("XY模型跑完再看XY模型")]
    assert anchors(words, {"race": "XY 模型"}) == {"race": 0.0}
    assert anchors(words, {"race": "XY，模型"}) == {"race": 0.0}  # punctuation copied from the text is ignored
    assert anchors(words, {"race": "XY模型"}, after=3) == {"race": 8.0}
    with pytest.raises(KeyError):
        anchors(words, {"x": "不存在"})
    with pytest.raises(ValueError):
        anchors(words, {"x": "，"})  # empty after stripping must not match the first word


def test_cli_anchors(tmp_path, capsys):
    tr = {"schema": "vlog.transcript/1", "text": "你好", "words": [{"text": "你", "start": 1.0, "end": 1.2, "punc": ""},
                                                                 {"text": "好", "start": 1.2, "end": 1.4, "punc": "。"}]}
    (tmp_path / "t.json").write_text(json.dumps(tr, ensure_ascii=False))
    assert cli.main(["anchors", str(tmp_path / "t.json"), "--phrase", "hi=你好"]) == 0
    assert json.loads(capsys.readouterr().out)["data"]["anchors"] == {"hi": 1.0}


def _words(text, step=0.2):
    out, t = [], 0.0
    for ch in text:
        if ch in "，。？":
            out[-1]["punc"] = ch
            continue
        out.append({"text": ch, "start": t, "end": t + step * 0.8, "punc": ""})
        t += step
    return out


def test_long_clause_is_split_evenly_without_orphans():
    cues = build_cues(_words("周末的时候我们一般会先去公园散步然后找个地方吃一顿简单的午饭。"), 20)
    lengths = [len(c["text"]) for c in cues]
    assert len(cues) == 2 and min(lengths) >= 10, cues


def test_clauses_are_packed_and_sentence_ends_respected():
    cues = build_cues(_words("他做了一张表，你可以让两个程序各自算一遍。下一句。"), 20)
    assert cues[-1]["text"] == "下一句"
    assert all(not c["text"].endswith(("，", "。")) for c in cues)


def test_long_clause_cuts_at_a_clause_opener_not_inside_a_word():
    # one clause, no punctuation, one character per aligner word (as CJK aligners emit)
    text = "我们今天先把这个问题的来龙去脉讲清楚然后再去看看具体有哪些解决方法。"
    cues = build_cues(_words(text), 20)
    pieces = [c["text"].rstrip("。") for c in cues]
    assert "".join(pieces) == text.rstrip("。")
    assert len(pieces) == 2
    assert pieces == ["我们今天先把这个问题的来龙去脉讲清楚", "然后再去看看具体有哪些解决方法"], pieces


def test_long_clause_without_an_opener_cuts_after_a_particle():
    text = "这是一个我们在很多地方都会遇到的非常具体而且非常麻烦的问题。"
    pieces = [c["text"].rstrip("。") for c in build_cues(_words(text), 16)]
    assert "".join(pieces) == text.rstrip("。") and len(pieces) == 2
    assert pieces[0].endswith(("的", "了", "是", "在")) or pieces[1].startswith("而且"), pieces


def test_no_cut_inside_a_glossary_key_and_every_piece_fits():
    text = "我们今天要讲的就是扣的瑞维有这件事情到底应该怎么去做才比较好。"
    glossary = {"扣的瑞维有": "code review"}
    for mw in (10, 12, 14, 16):
        cues = build_cues(_words(text), mw, glossary=glossary)
        joined = "".join(c["text"] for c in cues)
        assert "扣的" not in joined and "code review" in joined, cues
        assert all(c["text"].count("code review") in (0, 1) for c in cues)


def test_latin_clause_never_exceeds_max_width():
    from vlog_skill.subtitles import _width
    words, t = [], 0.0
    for w in "an english sentence with some extraordinarily long words that keeps going without any punctuation".split():
        words.append({"text": w, "start": t, "end": t + 0.3, "punc": ""})
        t += 0.4
    words[-1]["punc"] = "."
    for mw in (8, 10, 12, 16):
        cues = build_cues(words, mw)
        assert all(_width(c["text"]) <= mw for c in cues), (mw, cues)


def test_global_offset_finds_a_large_start_difference(tmp_path, capsys):
    # the "camera" starts 3.5 s before the "screen": both hear the same room
    rng = np.random.default_rng(7)
    room = (0.05 * rng.standard_normal((int(20 * SR), 2))).astype(np.float32)
    lead = int(3.5 * SR)
    write_wav(tmp_path / "screen.wav", room[lead:lead + int(12 * SR)], SR)
    write_wav(tmp_path / "cam.wav", room[: int(15 * SR)], SR)
    assert cli.main(["offset", str(tmp_path / "screen.wav"), str(tmp_path / "cam.wav"), "--global", "--window", "3"]) == 0
    out = json.loads(capsys.readouterr().out)
    data = out["data"]
    assert out["ok"] and data["aligned"]
    assert abs(data["start_delta_s"] + 3.5) < 0.002  # camera started earlier: negative
    assert data["confidence"] > 3 and abs(data["drift_ms_per_min"]) < 1


def test_offset_requires_at_without_global(tmp_path, capsys):
    rec = make_recording(WORDS, 4.0)
    write_wav(tmp_path / "a.wav", rec, SR)
    assert cli.main(["offset", str(tmp_path / "a.wav"), str(tmp_path / "a.wav")]) != 0
    assert not json.loads(capsys.readouterr().out)["ok"]
