"""Cut a short distribution clip from a finished video.

A clip is one or more source segments joined with a short crossfade, faded in and out (the fade-out
ends where the source material ends), optionally held on its last frame over silence and closed on a
branded end card (an image, or a frame of the source such as its title card) reached by a crossfade, loudness-normalised in two passes (linear when the true peak allows), and
encoded as H.264 High / yuv420p / AAC with the moov atom at the front. The command also reports, for
every segment edge, whether it falls inside a subtitle cue and how far the audio at the edge sits below
the segment's speech level (a music bed keeps absolute levels high, so the margin is relative), and it
writes first-frame, last-frame and contact-sheet stills for review.
"""

from __future__ import annotations

import json
import math
import re
import subprocess
import tempfile
from pathlib import Path

import numpy as np

from .audio import ToolError, load_audio, measure_loudness, require_ffmpeg, require_file, rms_db

EDGE_WINDOW_S = 0.10  # audio checked on both sides of an edge
MIN_EDGE_MARGIN_DB = 10.0  # edge level must sit this far below the segment's speech level (p90)
MIN_SPEECH_SPREAD_DB = 6.0  # p90 - median below this: the segment has no speech (title card over music)
CUE_TOLERANCE_S = 0.02
_TS = re.compile(r"(\d+):(\d{2}):(\d{2})[,.](\d{3})\s*-->\s*(\d+):(\d{2}):(\d{2})[,.](\d{3})")


def parse_segments(specs: list[str]) -> list[tuple[float, float]]:
    """'12.5:80' -> (12.5, 80.0). Each segment needs 0 <= start < end."""
    out = []
    for spec in specs:
        a, sep, b = spec.partition(":")
        if not sep:
            raise ValueError(f"--segment must be START:END in seconds, got {spec!r}")
        s, e = float(a), float(b)
        if not 0 <= s < e:
            raise ValueError(f"segment {spec!r} must satisfy 0 <= start < end")
        out.append((s, e))
    return out


def parse_srt(text: str) -> list[dict]:
    cues = []
    for block in re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip()):
        lines = block.split("\n")
        for i, line in enumerate(lines):
            m = _TS.search(line)
            if m:
                g = [int(x) for x in m.groups()]
                start = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000
                end = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000
                cues.append({"start": start, "end": end, "text": " ".join(lines[i + 1:]).strip()})
                break
    return sorted(cues, key=lambda c: c["start"])


def edge_against_cues(t: float, cues: list[dict]) -> dict:
    """Is a cut edge inside a subtitle cue? If so, name the cue; otherwise give the cue gap it sits in."""
    for c in cues:
        if c["start"] + CUE_TOLERANCE_S < t < c["end"] - CUE_TOLERANCE_S:
            return {"inside_cue": True, "cue": {"start": c["start"], "end": c["end"], "text": c["text"]}}
    prev_end = max((c["end"] for c in cues if c["end"] <= t + CUE_TOLERANCE_S), default=0.0)
    nxt = [c["start"] for c in cues if c["start"] >= t - CUE_TOLERANCE_S]
    return {"inside_cue": False, "gap": [round(prev_end, 3), round(min(nxt), 3) if nxt else None]}


def edge_margins(media: str, segments: list[tuple[float, float]]) -> list[dict]:
    """Speech level (p90 of the 10 ms RMS envelope) per segment and the loudest level near each edge."""
    sr, hop = 16000, 0.01
    out = []
    for s, e in segments:
        t0 = max(0.0, s - EDGE_WINDOW_S)
        x = load_audio(media, sr, 1, start=t0, duration=(e + EDGE_WINDOW_S) - t0)
        env = rms_db(x, sr, hop)
        if len(env) == 0:
            raise ValueError(f"no audio decoded for segment {s}:{e}")

        def idx(t):
            return int(np.clip(round((t - t0) / hop), 0, len(env)))

        body = env[idx(s):idx(e)]
        if len(body) == 0:
            raise ValueError(f"segment {s}:{e} decoded to no audio (decoded {len(x) / sr:.3f} s from {t0:.3f} s)")
        speech = float(np.percentile(body, 90))
        spread = speech - float(np.median(body))
        res = {"speech_p90_db": round(speech, 1), "spread_db": round(spread, 1),
               "has_speech": spread >= MIN_SPEECH_SPREAD_DB}
        for name, t in (("start", s), ("end", e)):
            win = env[idx(t - EDGE_WINDOW_S):max(idx(t + EDGE_WINDOW_S), idx(t - EDGE_WINDOW_S) + 1)]
            level = float(win.max())
            res[name] = {"level_db": round(level, 1), "margin_db": round(speech - level, 1)}
        out.append(res)
    return out


def probe(path: str | Path) -> dict:
    require_ffmpeg()
    require_file(path)
    proc = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
                          capture_output=True, text=True)
    if proc.returncode != 0:
        raise ToolError(f"ffprobe failed on {path}: {proc.stderr.strip()}")
    doc = json.loads(proc.stdout)
    v = next((s for s in doc["streams"] if s["codec_type"] == "video"), None)
    a = next((s for s in doc["streams"] if s["codec_type"] == "audio"), None)

    def rate(r):
        n, _, d = (r or "0/1").partition("/")
        return round(float(n) / float(d or 1), 3) if float(d or 1) else 0.0

    def raw_rate(stream):
        for key in ("avg_frame_rate", "r_frame_rate"):
            r = stream.get(key) or "0/0"
            n, _, d = r.partition("/")
            if float(n or 0) > 0 and float(d or 1) > 0:
                return r
        return None

    return {
        "duration_s": round(float(doc["format"]["duration"]), 3),
        "size_bytes": int(doc["format"].get("size", 0)),
        "video": None if v is None else {"codec": v["codec_name"], "profile": v.get("profile"), "pix_fmt": v.get("pix_fmt"),
                                         "width": v["width"], "height": v["height"], "fps": rate(raw_rate(v)),
                                         "fps_rational": raw_rate(v)},
        "audio": None if a is None else {"codec": a["codec_name"], "sample_rate": int(a["sample_rate"]), "channels": a["channels"]},
        "streams": [s["codec_type"] for s in doc["streams"]],
    }


def top_level_boxes(path: str | Path) -> list[str]:
    """Order of the top-level MP4 boxes; faststart means 'moov' precedes 'mdat'."""
    names = []
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        size_total = fh.tell()
        pos = 0
        while pos + 8 <= size_total:
            fh.seek(pos)
            head = fh.read(8)
            size, kind = int.from_bytes(head[:4], "big"), head[4:].decode("latin-1")
            if size == 1:
                size = int.from_bytes(fh.read(8), "big")
            elif size == 0:
                size = size_total - pos
            if size < 8:
                break
            names.append(kind)
            pos += size
    return names


def is_faststart(path: str | Path) -> bool:
    boxes = top_level_boxes(path)
    return "moov" in boxes and "mdat" in boxes and boxes.index("moov") < boxes.index("mdat")


def parse_end_card(spec: str | None) -> dict | None:
    """'1.5' (or 't=1.5') -> a frame of the source at 1.5 s; anything else -> an image path."""
    if not spec:
        return None
    raw = spec[2:] if spec.startswith("t=") else spec
    try:
        t = float(raw)
    except ValueError:
        require_file(spec)
        return {"kind": "image", "path": spec}
    if t < 0:
        raise ValueError(f"--end-card time must be >= 0, got {spec!r}")
    return {"kind": "source_frame", "t": t}


def timeline(segments: list[tuple[float, float]], crossfade: float, hold: float,
             card_s: float = 0.0, card_crossfade: float = 0.0) -> dict:
    """Output length and xfade offsets for segments joined with a crossfade of `crossfade` seconds.

    With an end card, the card crossfades in over the last `card_crossfade` seconds of body + hold and
    then stays fully visible for `card_s` seconds, so total = body + hold + card_s.
    """
    durs = [e - s for s, e in segments]
    if len(durs) > 1 and crossfade > 0 and min(durs) <= crossfade:
        raise ValueError(f"every segment must be longer than the crossfade ({crossfade} s)")
    offsets, length = [], durs[0]
    for d in durs[1:]:
        if crossfade > 0:
            offsets.append(round(length - crossfade, 4))
            length += d - crossfade
        else:
            length += d
    tl = {"durations": durs, "xfade_offsets": offsets, "body_s": length, "total_s": length + hold}
    if card_s > 0:
        if card_crossfade >= length + hold:
            raise ValueError(f"the end-card crossfade ({card_crossfade} s) must be shorter than the clip before it")
        tl["card_offset"] = round(length + hold - card_crossfade, 4)
        tl["card_input_s"] = card_s + card_crossfade
        tl["card_crossfade"] = card_crossfade
        tl["total_s"] = length + hold + card_s
    return tl


def _audio_chain(n: int, tl: dict, crossfade: float, hold: float, fade_in: float, fade_out: float) -> list[str]:
    f = [f"[{i}:a:0]asetpts=PTS-STARTPTS,aresample=48000,aformat=channel_layouts=stereo[a{i}]" for i in range(n)]
    cur = "a0"
    for i in range(1, n):
        if crossfade > 0:
            f.append(f"[{cur}][a{i}]acrossfade=d={crossfade}:c1=qsin:c2=qsin[ax{i}]")
        else:
            f.append(f"[{cur}][a{i}]concat=n=2:v=0:a=1[ax{i}]")
        cur = f"ax{i}"
    # The fade-out ends where the source material ends (body_s); a hold adds silence after it.
    # Fading over the hold instead would cut the bed off abruptly at body_s, since apad is silent.
    tail = [f"atrim=0:{tl['body_s']:.4f}"]
    if fade_in > 0:
        tail.append(f"afade=t=in:st=0:d={fade_in}")
    if fade_out > 0:
        tail.append(f"afade=t=out:st={max(0.0, tl['body_s'] - fade_out):.4f}:d={fade_out}")
    if tl["total_s"] > tl["body_s"]:
        tail.append(f"apad=whole_dur={tl['total_s']:.4f}")  # hold and end card are silent
    tail.append(f"atrim=0:{tl['total_s']:.4f}")
    f.append(f"[{cur}]{','.join(tail)}[apre]")
    return f


def _video_chain(n: int, tl: dict, fps: str, crossfade: float, hold: float, video_fade_out: float,
                 size: tuple[int, int] | None = None) -> list[str]:
    f = [f"[{i}:v:0]setpts=PTS-STARTPTS,fps={fps},settb=AVTB,format=yuv420p[v{i}]" for i in range(n)]
    cur = "v0"
    for i in range(1, n):
        if crossfade > 0:
            f.append(f"[{cur}][v{i}]xfade=transition=fade:duration={crossfade}:offset={tl['xfade_offsets'][i - 1]}[vx{i}]")
        else:
            f.append(f"[{cur}][v{i}]concat=n=2:v=1:a=0[vx{i}]")
        cur = f"vx{i}"
    tail = []
    if hold > 0:
        tail.append(f"tpad=stop_mode=clone:stop_duration={hold}")
    if "card_offset" in tl:  # input n is the end-card still, looped for card_input_s
        w, h = size
        f.append(f"[{cur}]{','.join(tail) or 'null'}[vbody]")
        f.append(f"[{n}:v:0]scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2,"
                 f"setsar=1,fps={fps},settb=AVTB,format=yuv420p[vcard]")
        f.append(f"[vbody][vcard]xfade=transition=fade:duration={tl['card_crossfade']}:offset={tl['card_offset']}[vwc]")
        cur, tail = "vwc", []
    if video_fade_out > 0:
        tail.append(f"fade=t=out:st={max(0.0, tl['total_s'] - video_fade_out):.4f}:d={video_fade_out}")
    tail.append(f"trim=0:{tl['total_s']:.4f}")
    f.append(f"[{cur}]{','.join(tail)}[vout]")
    return f


def _inputs(media: str, segments: list[tuple[float, float]]) -> list[str]:
    args = []
    for s, e in segments:
        args += ["-ss", f"{s:.4f}", "-t", f"{e - s:.4f}", "-i", str(media)]
    return args


def _render(inputs: list[str], graph: str, crf: int, audio_bitrate: str, out: str) -> subprocess.CompletedProcess:
    return _run(["ffmpeg", "-y", "-hide_banner", "-nostats", *inputs, "-filter_complex", graph,
                 "-map", "[vout]", "-map", "[aout]", "-map_metadata", "-1", "-map_chapters", "-1",
                 "-c:v", "libx264", "-profile:v", "high", "-preset", "medium", "-crf", str(crf),
                 "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000", "-ac", "2",
                 "-movflags", "+faststart", str(out)], "clip render")


def _run(cmd: list[str], what: str) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ToolError(f"ffmpeg {what} failed: {proc.stderr.strip()[-3000:]}")
    return proc


def _loudnorm_json(stderr: str) -> dict:
    start = stderr.rfind("{")
    end = stderr.rfind("}")
    if start < 0 or end < start:
        raise ToolError(f"loudnorm printed no JSON: {stderr.strip()[-1500:]}")
    return json.loads(stderr[start:end + 1])


def lra_target(input_lra: float) -> int:
    """loudnorm falls back to dynamic mode when the input's LRA exceeds the target LRA, so raise the target."""
    return int(min(50, max(11, math.ceil(input_lra) + 1)))


def linear_blockers(m1: dict, lufs: float, true_peak: float, lra: float) -> list[dict]:
    """Conditions under which loudnorm's linear mode cannot hold (it then switches to dynamic)."""
    reasons = []
    tp_after = float(m1["input_tp"]) + (lufs - float(m1["input_i"]))
    if tp_after > true_peak:
        reasons.append({"condition": "true_peak", "input_tp": float(m1["input_tp"]), "input_i": float(m1["input_i"]),
                        "true_peak_after_gain": round(tp_after, 2), "limit": true_peak})
    if float(m1["input_lra"]) > lra:
        reasons.append({"condition": "lra", "input_lra": float(m1["input_lra"]), "target_lra": lra})
    return reasons


def write_stills(clip: str | Path, stills_dir: str | Path, frames: int = 12, cols: int = 4) -> dict:
    """First frame, last frame, and a contact sheet of `frames` evenly spaced frames (first to last)."""
    clip, stills_dir = Path(clip), Path(stills_dir)
    stills_dir.mkdir(parents=True, exist_ok=True)
    stem = clip.stem
    first, last, sheet = stills_dir / f"{stem}_first.png", stills_dir / f"{stem}_last.png", stills_dir / f"{stem}_sheet.png"
    _run(["ffmpeg", "-y", "-v", "error", "-i", str(clip), "-frames:v", "1", str(first)], "first frame")
    _run(["ffmpeg", "-y", "-v", "error", "-sseof", "-0.5", "-i", str(clip), "-update", "1", str(last)], "last frame")
    dur = probe(clip)["duration_s"]
    times = [round(k * max(dur - 0.08, 0.0) / max(frames - 1, 1), 3) for k in range(frames)]
    rows = math.ceil(frames / cols)
    with tempfile.TemporaryDirectory() as tmp:
        for k, t in enumerate(times):
            _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{t}", "-i", str(clip), "-frames:v", "1",
                  "-vf", "scale=480:-2", str(Path(tmp) / f"f{k:03d}.png")], f"sheet frame at {t}s")
        _run(["ffmpeg", "-y", "-v", "error", "-i", str(Path(tmp) / "f%03d.png"),
              "-vf", f"tile={cols}x{rows}:padding=6:color=white", "-frames:v", "1", str(sheet)], "contact sheet")
    return {"first": str(first), "last": str(last), "sheet": str(sheet), "sheet_times_s": times}


def cut_clip(
    media: str,
    out: str,
    segments: list[tuple[float, float]],
    *,
    srt: str | None = None,
    crossfade: float = 0.3,
    hold: float = 0.0,
    end_card: str | None = None,
    end_card_s: float = 2.5,
    end_card_crossfade: float = 0.5,
    fade_in: float = 0.15,
    fade_out: float = 0.5,
    video_fade_out: float = 0.0,
    lufs: float = -16.0,
    true_peak: float = -1.0,
    max_duration: float | None = 140.0,
    crf: int = 16,
    audio_bitrate: str = "192k",
    stills_dir: str | None = None,
    sheet_frames: int = 12,
) -> dict:
    require_ffmpeg()
    require_file(media)
    src = probe(media)
    if src["video"] is None or src["audio"] is None:
        raise ValueError(f"{media} needs one video and one audio stream, found {src['streams']}")
    for s, e in segments:
        if e > src["duration_s"] + 0.05:
            raise ValueError(f"segment {s}:{e} ends after the source ({src['duration_s']} s)")
    n = len(segments)
    crossfade = crossfade if n > 1 else 0.0
    card = parse_end_card(end_card)
    if card and card["kind"] == "source_frame" and card["t"] > src["duration_s"]:
        raise ValueError(f"--end-card time {card['t']} s is after the end of the source ({src['duration_s']} s)")
    tl = timeline(segments, crossfade, hold, end_card_s if card else 0.0, end_card_crossfade if card else 0.0)
    warnings = []

    cues = parse_srt(Path(srt).read_text(encoding="utf-8")) if srt else None
    margins = edge_margins(media, segments)
    seg_reports = []
    for (s, e), m in zip(segments, margins):
        rep = {"start": s, "end": e, "duration_s": round(e - s, 3), "speech_p90_db": m["speech_p90_db"],
               "spread_db": m["spread_db"], "has_speech": m["has_speech"]}
        for name, t in (("start", s), ("end", e)):
            edge = {"t": t, **m[name]}
            if cues is not None:
                edge.update(edge_against_cues(t, cues))
                if edge["inside_cue"]:
                    warnings.append({"type": "edge_inside_cue", "t": t, "cue": edge["cue"]})
            if m["has_speech"] and edge["margin_db"] < MIN_EDGE_MARGIN_DB:
                warnings.append({"type": "edge_in_speech", "t": t, "margin_db": edge["margin_db"]})
            rep[f"{name}_edge"] = edge
        if not m["has_speech"]:
            warnings.append({"type": "edge_check_skipped", "segment": [s, e], "spread_db": m["spread_db"],
                             "reason": f"p90 - median below {MIN_SPEECH_SPREAD_DB} dB: no speech found, edges not checked"})
        seg_reports.append(rep)
    if card and card["kind"] == "source_frame" and cues is not None:
        where = edge_against_cues(card["t"], cues)
        if where["inside_cue"]:
            warnings.append({"type": "end_card_inside_cue", "t": card["t"], "cue": where["cue"]})

    fps = src["video"]["fps_rational"] or "25"
    inputs = _inputs(media, segments)
    achain = _audio_chain(n, tl, crossfade, hold, fade_in, fade_out)

    # Pass 1: measure the joined, faded audio.
    measure = ";".join(achain) + f";[apre]loudnorm=I={lufs}:TP={true_peak}:LRA=11:print_format=json[ameas]"
    p1 = _run(["ffmpeg", "-hide_banner", "-nostats", *inputs, "-filter_complex", measure, "-map", "[ameas]",
               "-f", "null", "-"], "loudness measurement")
    m1 = _loudnorm_json(p1.stderr)

    # Pass 2: render with the measured values (linear gain when the true peak and LRA allow it).
    lra = lra_target(float(m1["input_lra"]))
    norm = (f"loudnorm=I={lufs}:TP={true_peak}:LRA={lra}:measured_I={m1['input_i']}:measured_TP={m1['input_tp']}"
            f":measured_LRA={m1['input_lra']}:measured_thresh={m1['input_thresh']}:offset={m1['target_offset']}"
            f":linear=true:print_format=json,aresample=48000")
    size = (src["video"]["width"], src["video"]["height"])
    graph = (";".join(_video_chain(n, tl, fps, crossfade, hold, video_fade_out, size) + achain)
             + f";[apre]{norm}[aout]")
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        card_inputs = []
        if card:
            still = card["path"] if card["kind"] == "image" else str(Path(tmp) / "end_card.png")
            if card["kind"] == "source_frame":
                _run(["ffmpeg", "-y", "-v", "error", "-ss", f"{card['t']:.4f}", "-i", str(media), "-frames:v", "1",
                      still], "end-card frame")
            card_inputs = ["-loop", "1", "-framerate", fps, "-t", f"{tl['card_input_s']:.4f}", "-i", still]
        p2 = _render(inputs + card_inputs, graph, crf, audio_bitrate, out)
    normalization = _loudnorm_json(p2.stderr).get("normalization_type")
    if normalization != "linear":
        warnings.append({"type": "loudnorm_not_linear", "normalization_type": normalization,
                         "reasons": linear_blockers(m1, lufs, true_peak, lra),
                         "hint": "true_peak: lower --lufs or raise --true-peak; lra: the material is very dynamic"})

    res = probe(out)
    loud = measure_loudness(out)
    fast = is_faststart(out)
    if not fast:
        warnings.append({"type": "not_faststart"})
    if loud["integrated_lufs"] is None or abs(loud["integrated_lufs"] - lufs) > 0.5:
        warnings.append({"type": "loudness_off_target", "integrated_lufs": loud["integrated_lufs"], "target_lufs": lufs})
    if loud["true_peak_dbfs"] is None or loud["true_peak_dbfs"] > true_peak + 0.1:
        warnings.append({"type": "true_peak_over", "true_peak_dbfs": loud["true_peak_dbfs"], "limit_dbfs": true_peak})
    if res["streams"] != ["video", "audio"]:
        warnings.append({"type": "extra_streams", "streams": res["streams"]})
    if max_duration is not None and res["duration_s"] > max_duration:
        warnings.append({"type": "over_max_duration", "duration_s": res["duration_s"], "max_duration_s": max_duration})
    if abs(res["duration_s"] - tl["total_s"]) > 0.15:
        warnings.append({"type": "duration_mismatch", "expected_s": round(tl["total_s"], 3), "actual_s": res["duration_s"]})
    stills = write_stills(out, stills_dir or Path(out).parent, sheet_frames) if sheet_frames > 0 else None
    return {
        "out": str(out),
        "source": {"path": str(media), "duration_s": src["duration_s"], "video": src["video"]},
        "segments": seg_reports,
        "crossfade_s": crossfade,
        "hold_s": hold,
        "end_card": None if not card else {**card, "duration_s": end_card_s, "crossfade_s": end_card_crossfade,
                                           "starts_at_s": tl["card_offset"]},
        "expected_duration_s": round(tl["total_s"], 3),
        "duration_s": res["duration_s"],
        "size_bytes": res["size_bytes"],
        "video": res["video"],
        "audio": res["audio"],
        "streams": res["streams"],
        "faststart": fast,
        "loudness": loud,
        "loudness_target": {"integrated_lufs": lufs, "true_peak_dbfs": true_peak, "lra": lra,
                            "normalization_type": normalization},
        "stills": stills,
        "warnings": warnings,
    }
