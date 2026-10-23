import json
import subprocess

import numpy as np
import pytest

from synth import SR, make_recording
from vlog_skill import cli
from vlog_skill.audio import write_wav
from vlog_skill.clip import (
    edge_against_cues,
    parse_segments,
    parse_srt,
    probe,
    timeline,
    top_level_boxes,
)

# 0.1 s "syllables" every 0.25 s (so the envelope has speech-like gaps), a quiet gap at 2.5-2.9 s and another at 4.9-5.3 s; room tone elsewhere.
WORDS = [(c, 0.5 + i * 0.25, 0.6 + i * 0.25, 220 + 30 * i, "") for i, c in enumerate("一二三四五六七八")]
WORDS += [(c, 2.9 + i * 0.25, 3.0 + i * 0.25, 300 + 30 * i, "") for i, c in enumerate("甲乙丙丁戊己庚辛")]
WORDS += [(c, 5.3 + i * 0.25, 5.4 + i * 0.25, 400 + 30 * i, "") for i, c in enumerate("子丑寅卯")]
SRT = """1
00:00:00,500 --> 00:00:02,450
一二三四五六七八

2
00:00:02,900 --> 00:00:04,850
甲乙丙丁戊己庚辛

3
00:00:05,300 --> 00:00:06,250
子丑寅卯
"""


@pytest.fixture(scope="module")
def video(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("clip")
    write_wav(tmp / "voice.wav", make_recording(WORDS, 7.0), SR)
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=7",
         "-i", str(tmp / "voice.wav"), "-shortest", "-c:v", "libx264", "-pix_fmt", "yuv420p",
         "-c:a", "aac", str(tmp / "film.mp4")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    (tmp / "film.srt").write_text(SRT, encoding="utf-8")
    return tmp


def test_parse_segments():
    assert parse_segments(["0.9:95.15", "1:2"]) == [(0.9, 95.15), (1.0, 2.0)]
    for bad in ("5", "3:2", "-1:2"):
        with pytest.raises(ValueError):
            parse_segments([bad])


def test_edges_against_cues():
    cues = parse_srt(SRT)
    assert [c["text"] for c in cues] == ["一二三四五六七八", "甲乙丙丁戊己庚辛", "子丑寅卯"]
    assert edge_against_cues(2.7, cues) == {"inside_cue": False, "gap": [2.45, 2.9]}
    inside = edge_against_cues(4.0, cues)
    assert inside["inside_cue"] and inside["cue"]["text"] == "甲乙丙丁戊己庚辛"
    assert edge_against_cues(6.5, cues) == {"inside_cue": False, "gap": [6.25, None]}


def test_timeline_with_crossfade_and_hold():
    tl = timeline([(1.0, 3.0), (10.0, 20.0)], crossfade=0.3, hold=1.0)
    assert tl["xfade_offsets"] == [1.7]
    assert tl["body_s"] == pytest.approx(11.7) and tl["total_s"] == pytest.approx(12.7)
    with pytest.raises(ValueError):
        timeline([(0.0, 0.2), (1.0, 2.0)], crossfade=0.3, hold=0.0)


def test_top_level_boxes(tmp_path):
    def box(kind, payload=b""):
        return (8 + len(payload)).to_bytes(4, "big") + kind + payload

    (tmp_path / "fast.mp4").write_bytes(box(b"ftyp", b"isom") + box(b"moov", b"x" * 10) + box(b"mdat", b"y" * 20))
    (tmp_path / "slow.mp4").write_bytes(box(b"ftyp", b"isom") + box(b"mdat", b"y" * 20) + box(b"moov", b"x" * 10))
    assert top_level_boxes(tmp_path / "fast.mp4") == ["ftyp", "moov", "mdat"]
    assert top_level_boxes(tmp_path / "slow.mp4") == ["ftyp", "mdat", "moov"]


def test_clip_end_to_end(video, capsys):
    out = video / "out" / "teaser.mp4"
    rc = cli.main(["clip", str(video / "film.mp4"), "--out", str(out), "--segment", "0.3:2.7", "--segment", "2.7:5.1",
                   "--srt", str(video / "film.srt"), "--hold-end", "0.5", "--sheet-frames", "4"])
    env = json.loads(capsys.readouterr().out)
    assert rc == 0, env
    d = env["data"]
    assert d["warnings"] == []
    assert d["expected_duration_s"] == pytest.approx(2.4 + 2.4 - 0.3 + 0.5)
    assert abs(d["duration_s"] - d["expected_duration_s"]) < 0.15
    assert d["video"]["codec"] == "h264" and d["video"]["profile"] == "High" and d["video"]["pix_fmt"] == "yuv420p"
    assert d["audio"]["codec"] == "aac" and d["streams"] == ["video", "audio"]
    assert d["faststart"]
    assert d["segments"][0]["has_speech"] and d["segments"][0]["end_edge"]["margin_db"] > 10
    assert abs(d["loudness"]["integrated_lufs"] - (-16.0)) < 1.5
    for key in ("first", "last", "sheet"):
        assert (video / "out" / f"teaser_{key}.png").is_file()
    assert probe(out)["duration_s"] == d["duration_s"]


def test_clip_flags_edges_inside_speech_and_cues(video, capsys):
    out = video / "out" / "bad.mp4"
    rc = cli.main(["clip", str(video / "film.mp4"), "--out", str(out), "--segment", "0.3:3.5",
                   "--srt", str(video / "film.srt"), "--sheet-frames", "0", "--max-duration", "2"])
    d = json.loads(capsys.readouterr().out)["data"]
    assert rc == 0
    kinds = {w["type"] for w in d["warnings"]}
    assert {"edge_inside_cue", "edge_in_speech", "over_max_duration"} <= kinds
    assert d["stills"] is None


def test_clip_rejects_segment_past_the_end(video, capsys):
    rc = cli.main(["clip", str(video / "film.mp4"), "--out", str(video / "x.mp4"), "--segment", "1:30"])
    env = json.loads(capsys.readouterr().out)
    assert rc == cli.EXIT_INPUT and env["error"]["type"] == "ValueError"


@pytest.fixture(scope="module")
def bed_film(tmp_path_factory):
    """A continuous tone bed (no speech) with a title tag and two chapters in the container."""
    tmp = tmp_path_factory.mktemp("bed")
    (tmp / "meta.txt").write_text(
        ";FFMETADATA1\ntitle=Private working title\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=0\nEND=3000\ntitle=Part one\n"
        "[CHAPTER]\nTIMEBASE=1/1000\nSTART=3000\nEND=6000\ntitle=Part two\n", encoding="utf-8")
    proc = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc2=size=320x180:rate=25:duration=6",
         "-f", "lavfi", "-i", "sine=frequency=220:sample_rate=48000:duration=6",
         "-i", str(tmp / "meta.txt"), "-map", "0:v", "-map", "1:a", "-map_metadata", "2", "-map_chapters", "2",
         "-af", "volume=0.25", "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", str(tmp / "bed.mp4")],
        capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    return tmp


def _rms_db(x):
    return 20 * np.log10(np.sqrt(np.mean(np.asarray(x, dtype=np.float64) ** 2)) + 1e-9)


def test_hold_end_fades_before_the_hold(bed_film, capsys):
    from vlog_skill.audio import load_audio

    out = bed_film / "held.mp4"
    rc = cli.main(["clip", str(bed_film / "bed.mp4"), "--out", str(out), "--segment", "0.5:4.5",
                   "--hold-end", "1.0", "--fade-out", "0.5", "--sheet-frames", "0"])
    d = json.loads(capsys.readouterr().out)["data"]
    assert rc == 0
    body = 4.0
    x = load_audio(out, 48000, 1)
    seg = lambda a, b: x[int(a * 48000):int(b * 48000)]  # noqa: E731
    steady = _rms_db(seg(body - 1.2, body - 0.7))   # before the fade starts
    tail = _rms_db(seg(body - 0.1, body))           # last 100 ms of the source material
    hold = _rms_db(seg(body + 0.2, body + 0.9))     # inside the hold
    assert steady > -30
    assert tail < steady - 12, (steady, tail)       # faded, not cut off at full level
    assert hold < -70
    assert abs(d["duration_s"] - 5.0) < 0.15


def test_metadata_and_chapters_are_dropped(bed_film, capsys):
    out = bed_film / "clean.mp4"
    rc = cli.main(["clip", str(bed_film / "bed.mp4"), "--out", str(out), "--segment", "1:5", "--sheet-frames", "0"])
    d = json.loads(capsys.readouterr().out)["data"]
    assert rc == 0
    src = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-of", "json",
                                     str(bed_film / "bed.mp4")], capture_output=True, text=True).stdout)
    assert len(src["chapters"]) == 2 and src["format"]["tags"]["title"] == "Private working title"
    doc = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_chapters", "-show_format", "-show_streams",
                                     "-of", "json", str(out)], capture_output=True, text=True).stdout)
    assert doc["chapters"] == []
    assert "title" not in doc["format"].get("tags", {})
    assert [s["codec_type"] for s in doc["streams"]] == ["video", "audio"]
    kinds = {w["type"] for w in d["warnings"]}
    assert "extra_streams" not in kinds
    assert "edge_check_skipped" in kinds  # a tone bed has no speech, so its edges cannot be judged


def test_loudnorm_linear_blockers():
    from vlog_skill.clip import linear_blockers, lra_target

    assert lra_target(4.5) == 11 and lra_target(12.2) == 14 and lra_target(80) == 50
    m = {"input_i": "-16.0", "input_tp": "-1.5", "input_lra": "5.0"}
    assert linear_blockers(m, -16.0, -1.0, 11) == []
    tp = linear_blockers(m, -15.0, -1.0, 11)
    assert [r["condition"] for r in tp] == ["true_peak"] and tp[0]["true_peak_after_gain"] == -0.5
    lra = linear_blockers({**m, "input_lra": "15.0"}, -16.0, -1.0, 11)
    assert [r["condition"] for r in lra] == ["lra"]
