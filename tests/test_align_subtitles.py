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
    words = [{"text": c, "start": float(i), "end": i + 0.5} for i, c in enumerate("AB赛马跑完再看AB赛马")]
    assert anchors(words, {"race": "AB 赛马"}) == {"race": 0.0}
    assert anchors(words, {"race": "AB赛马"}, after=3) == {"race": 8.0}
    with pytest.raises(KeyError):
        anchors(words, {"x": "不存在"})


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
    cues = build_cues(_words("因为你让机器重新做一遍这个玩意儿特别便宜基本上是免费的。"), 20)
    lengths = [len(c["text"]) for c in cues]
    assert len(cues) == 2 and min(lengths) >= 10, cues


def test_clauses_are_packed_and_sentence_ends_respected():
    cues = build_cues(_words("你做一个报表，你完全可以让两个AI各自算一遍。下一句。"), 20)
    assert cues[-1]["text"] == "下一句"
    assert all(not c["text"].endswith(("，", "。")) for c in cues)
