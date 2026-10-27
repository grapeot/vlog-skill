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


def _speechlike(seconds: float, seed: int) -> np.ndarray:
    """Noise bursts with a syllable-like envelope, so the energy envelope has structure."""
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    spec = np.fft.rfft(rng.standard_normal(n))
    spec[np.fft.rfftfreq(n, 1.0 / SR) > 2000] = 0.0  # speech-like band: sub-sample shifts stay correlated
    x = np.fft.irfft(spec, n)
    x /= x.std()
    env = np.zeros(n)
    t = 0
    while t < n:
        dur = int(rng.uniform(0.08, 0.35) * SR)
        env[t:t + dur] = rng.uniform(0.2, 1.0)
        t += dur + int(rng.uniform(0.03, 0.4) * SR)
    return (0.1 * x * env).astype(np.float32)


def _global(capsys, ref, other, *extra):
    code = cli.main(["offset", str(ref), str(other), "--global", *extra])
    return code, json.loads(capsys.readouterr().out)


def test_global_offset_finds_a_large_start_difference(tmp_path, capsys):
    room = _speechlike(40, 7)
    lead = int(3.5 * SR)  # the "camera" starts 3.5 s before the "screen"
    write_wav(tmp_path / "screen.wav", np.stack([room[lead:lead + 30 * SR]] * 2, 1), SR)
    write_wav(tmp_path / "cam.wav", np.stack([room[: 34 * SR]] * 2, 1), SR)
    code, out = _global(capsys, tmp_path / "screen.wav", tmp_path / "cam.wav")
    data = out["data"]
    assert code == 0 and data["aligned"], data
    assert abs(data["start_delta_s"] + 3.5) < 0.002  # camera started earlier: negative
    assert data["confidence"] > 3 and abs(data["drift_ms_per_min"]) < 1


def test_global_offset_positive_delta_with_hum(tmp_path, capsys):
    room = _speechlike(45, 11)
    t = np.arange(len(room)) / SR
    hum = (0.2 * np.sin(2 * np.pi * 60 * t)).astype(np.float32)  # mains hum stronger than the speech
    write_wav(tmp_path / "ref.wav", np.stack([room[:35 * SR] + hum[:35 * SR]] * 2, 1), SR)
    later = int(5.0 * SR)  # other starts 5 s after the reference
    write_wav(tmp_path / "other.wav", np.stack([room[later:later + 30 * SR] + hum[:30 * SR]] * 2, 1), SR)
    code, out = _global(capsys, tmp_path / "ref.wav", tmp_path / "other.wav")
    data = out["data"]
    assert data["aligned"], data
    assert abs(data["start_delta_s"] - 5.0) < 0.002


def test_global_offset_measures_drift(tmp_path, capsys):
    room = _speechlike(130, 3)
    ref = room[: 120 * SR]
    # other runs 50 ppm fast and starts 2 s after the reference
    t_other = 2.0 + np.arange(int(110 * SR)) / SR * (1 + 50e-6)
    other = np.interp(t_other, np.arange(len(room)) / SR, room).astype(np.float32)
    write_wav(tmp_path / "ref.wav", np.stack([ref] * 2, 1), SR)
    write_wav(tmp_path / "other.wav", np.stack([other] * 2, 1), SR)
    code, out = _global(capsys, tmp_path / "ref.wav", tmp_path / "other.wav", "--points", "6")
    data = out["data"]
    assert data["aligned"], data
    assert abs(data["start_delta_s"] - 2.0) < 0.003
    assert abs(data["drift_ms_per_min"] - 3.0) < 0.5  # 50 ppm = 3 ms per minute


def test_global_offset_rejects_unrelated_recordings(tmp_path, capsys):
    write_wav(tmp_path / "a.wav", np.stack([_speechlike(30, 1)] * 2, 1), SR)
    write_wav(tmp_path / "b.wav", np.stack([_speechlike(30, 2)] * 2, 1), SR)
    code, out = _global(capsys, tmp_path / "a.wav", tmp_path / "b.wav")
    assert code == 0 and not out["data"]["aligned"] and out["data"]["reason"]


def test_global_offset_reports_short_overlap(tmp_path, capsys):
    write_wav(tmp_path / "a.wav", np.stack([_speechlike(5, 1)] * 2, 1), SR)
    code, out = _global(capsys, tmp_path / "a.wav", tmp_path / "a.wav")
    assert not out["data"]["aligned"] and "window" in out["data"]["reason"]


@pytest.mark.parametrize("args", [
    [],                                   # neither --at nor --global
    ["--at", "0.5", "--global"],          # both
    ["--at", "0.5", "--points", "3"],     # --points without --global
    ["--global", "--window", "0"],        # non-positive window
])
def test_offset_argument_combinations_are_usage_errors(tmp_path, capsys, args):
    rec = make_recording(WORDS, 4.0)
    write_wav(tmp_path / "a.wav", rec, SR)
    code = cli.main(["offset", str(tmp_path / "a.wav"), str(tmp_path / "a.wav"), *args])
    out = json.loads(capsys.readouterr().out)
    assert code == cli.EXIT_USAGE and out["error"]["type"] == "UsageError"


def test_offset_at_mode_through_cli_is_unchanged(tmp_path, capsys):
    rec = make_recording(WORDS, 6.0)
    write_wav(tmp_path / "a.wav", rec, SR)
    assert cli.main(["offset", str(tmp_path / "a.wav"), str(tmp_path / "a.wav"), "--at", "0.5", "--window", "5"]) == 0
    data = json.loads(capsys.readouterr().out)["data"]
    assert data["aligned"] and abs(data["points"][0]["offset_ms"]) < 1
