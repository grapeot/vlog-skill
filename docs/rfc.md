# Request for Comments: `vlog-skill` Architecture and Specifications

## 1. Architecture and Data Flow

`vlog-skill` separates deterministic media processing (the `vlog` Python CLI) from editorial and orchestration judgment (the agent skill in `skills/vlog/SKILL.md` and human checkpoints).

All state is exchanged through files in a project workspace outside the code repository:

```text
/path/to/project/
├── research/
│   └── source_contract.md     # Facts, sources, claim strengths, author judgments
├── writing/
│   ├── brief.md               # Audience, thesis, section plan, length budget
│   └── script.md              # Narration script with stable paragraph IDs (P01...)
├── audio/
│   ├── raw/
│   │   └── take1.m4a          # Continuous human voice recording
│   ├── edited.wav             # Rendered 48 kHz PCM edit
│   └── edited.m4a             # Rendered AAC edit for listening and the HeyGen web UI
├── asr/
│   ├── raw.json               # vlog.transcript/1 of audio/raw/take1.m4a
│   ├── edited.json            # vlog.transcript/1 of audio/edited.wav
│   └── avatar.json            # vlog.transcript/1 of avatar/avatar.mp4 (picture clock)
├── edit/
│   ├── edit_plan.json         # vlog.edit_plan/1 (cuts, room tone, pacing)
│   ├── manifest.json          # vlog.manifest/1 (kept islands, raw<->out map, loudness)
│   ├── verify_report.json     # vlog.verify/1 (join checks, absent phrase checks)
│   └── verify_report.md       # Human-readable verification table
├── avatar/
│   └── avatar.mp4             # HeyGen lip-synced avatar video
├── subtitles/
│   ├── glossary.json          # ASR term replacement rules
│   └── subtitles.srt          # Generated SRT subtitles
├── storyboard/
│   └── storyboard.md          # Visual plan keyed to asr/avatar.json phrases
├── broll/                     # Procedural frames, illustrations, screen captures
└── render/                    # Final composited video and QA artifacts (v0.2)
```

### Data Flow Diagram

```text
[audio/raw/take1.m4a]
        │
        ├──► vlog transcribe ──► [asr/raw.json] ──► vlog utterances
        │                              │
        ├──► vlog quiet                ▼
        │        │             [edit/edit_plan.json]
        │        └─────────────────────┤
        ▼                              ▼
        └───────► vlog edit ◄──────────┘
                      │
                      ├──► [audio/edited.wav], [audio/edited.m4a]
                      ├──► [edit/manifest.json]
                      ▼
               vlog transcribe ──► [asr/edited.json]
                                       │
                                       ▼
                                  vlog verify ──► [edit/verify_report.json], [edit/verify_report.md]
                                       │
                              (Human listens & approves)
                                       │
                                       ▼
                           HeyGen web UI / official heygen CLI
                                       │
                                       ▼
                              [avatar/avatar.mp4]
                                       │
                                       ▼
                                vlog transcribe ──► [asr/avatar.json]
                                                        │
                                       ┌────────────────┴────────────────┐
                                       ▼                                 ▼
                                vlog subtitles               [storyboard/storyboard.md]
                                       │
                                       ▼
                            [subtitles/subtitles.srt]
```

**Design Decision on `vlog subtitles`**: Included in v0.1 (`vlog_skill/subtitles.py`). It operates purely on `vlog.transcript/1` and a JSON glossary using the Python standard library, requiring no extra native dependencies.

---

## 2. Module Responsibilities

Package root: `vlog_skill/`. Target runtime: Python 3.12 with `numpy` and system `ffmpeg`/`ffprobe` on `PATH`.

| Module | Responsibility |
| :--- | :--- |
| `vlog_skill/project.py` | Implements `vlog init <project_dir>`. Creates the project layout (`research`, `writing`, `audio/raw`, `audio/music`, `asr`, `edit`, `avatar`, `storyboard`, `subtitles`, `broll`, `render`, `qa`) and `project.json`. Refuses (exit 4) to create a project inside the vlog-skill checkout, so recordings and transcripts cannot land in the public repository. |
| `vlog_skill/audio.py` | Thin subprocess wrapper around `ffmpeg` and `ffprobe`. Probes duration with `ffprobe`, decodes any media to float32 numpy arrays (mono or stereo) at a given rate, writes 16-bit PCM WAV, encodes AAC M4A, computes RMS envelopes, and parses integrated loudness, loudness range and true peak from `ffmpeg -af ebur128=peak=true`. A missing input raises `FileNotFoundError` (exit 4); an ffmpeg failure raises `ToolError` (exit 5) carrying ffmpeg's stderr. |
| `vlog_skill/transcribe.py` | Implements `vlog transcribe <media> --out <json>`. If `<media>` is a video container, extracts a temporary WAV via `audio.py`. Dynamically imports `mlx_qwen3_asr` (raising exit code `3` if the optional `[asr]` extra is not installed), runs `Qwen3-ASR-1.7B` with `Qwen3-ForcedAligner-0.6B`, attaches punctuation marks to preceding word tokens, and writes `vlog.transcript/1`. |
| `vlog_skill/utterances.py` | Implements `vlog utterances <transcript.json>`. Groups consecutive words from `vlog.transcript/1` into utterances split where the gap between words exceeds `--min-gap` (default 0.35 s); gaps of `--long-gap` (default 0.8 s) or more are bracketed in the table. Returns structured utterance records and formats a compact timing table. |
| `vlog_skill/quiet.py` | Implements `vlog quiet <audio> --start <s_float> --end <s_float> [--threshold-db <float>]`. Slices the waveform over `[start, end]`, computes a 10 ms non-overlapping RMS envelope in dBFS (`20 * log10(rms + 1e-9)`), and merges contiguous windows below `--threshold-db` (default -40 dBFS) lasting at least `--min-duration` (default 0.03 s) into quiet runs `{start, end, duration, min_db, center}`. `--envelope` also prints the envelope. |
| `vlog_skill/edit.py` | Implements `vlog edit <edit_plan.json>`. Filters cut words, groups kept words into islands, refines island boundaries using local RMS energy clamped to cut and neighbor boundaries, inserts room-tone pauses according to the pacing table, joins segments with 25 ms equal-power crossfades, writes WAV and M4A outputs, measures loudness, reports cut edges that sit inside speech energy, and emits `vlog.manifest/1`. |
| `vlog_skill/verify.py` | Implements `vlog verify`. Reads `manifest.json` (which carries the cuts and islands), `raw.json`, and `edited.json`. Extracts text windows around every join that crosses a cut, flags fillers or doubled characters near joins as `"review"`, searches the entire edited transcript for `--expect-absent` phrases, and writes `vlog.verify/1` JSON and Markdown reports. |
| `vlog_skill/align.py` | Implements `vlog offset` (audio cross-correlation at several points, positive offset = the other file is late; `--global` for recordings that started far apart, reporting `start_delta_s` = other start minus reference start, the opposite sign) and `vlog anchors` (phrase to the start time of its first word, spaces ignored, missing phrases raise). |
| `vlog_skill/subtitles.py` | Implements `vlog subtitles <transcript.json> [--glossary <glossary.json>] --out <srt>`. Applies glossary replacements to each cue's text, splits cues at punctuation up to ~22 CJK characters per cue without crossing sentence boundaries, and writes UTF-8 `.srt`. |
| `vlog_skill/clip.py` | Implements `vlog clip <video> --out <mp4> --segment START:END [...]`. See section 4.5. |
| `vlog_skill/cli.py` | `argparse` dispatcher for `vlog`. Catches typed exceptions, formats the standard JSON output envelope on stdout, and exits with deterministic codes (`0`, `2`, `3`, `4`, `5`). |

---

## 3. Data Schemas

All examples below are real output of the synthetic demo in `examples/synthetic_demo/` (paths shortened), except where marked.

### 3.1 Transcript (`vlog.transcript/1`)

Produced by `vlog transcribe`; consumed by `utterances`, `edit`, `verify`, and `subtitles`. Any engine can be used if its output is converted to this shape. `normalize()` also accepts a raw `mlx-qwen3-asr` dump (`segments` plus `chunks`) and converts it.

```json
{
  "schema": "vlog.transcript/1",
  "media": "audio/raw/take1.wav",
  "duration_s": 10.0,
  "engine": {"name": "mlx-qwen3-asr", "model": "Qwen/Qwen3-ASR-1.7B", "aligner": "Qwen/Qwen3-ForcedAligner-0.6B"},
  "language": "Chinese",
  "truncated": false,
  "text": "我们，看那错要要好。完。",
  "words": [
    {"text": "我", "start": 1.0, "end": 1.2, "punc": ""},
    {"text": "们", "start": 1.25, "end": 1.45, "punc": "，"}
  ]
}
```

- `words[i].punc` is the punctuation that follows the word in the engine's text. The aligner emits words without punctuation; `attach_punctuation()` recovers it by walking the chunk texts. Pacing and subtitle chunking depend on it.
- For Chinese the aligner emits one word per character.

### 3.2 Edit plan (`vlog.edit_plan/1`)

Written by the agent; consumed by `vlog edit`. Relative paths resolve against the directory that contains the plan file.

```json
{
  "schema": "vlog.edit_plan/1",
  "source_audio": "../audio/raw/take1.wav",
  "transcript": "../asr/raw.json",
  "output_wav": "../audio/edited.wav",
  "output_m4a": "../audio/edited.m4a",
  "manifest": "manifest.json",
  "sample_rate": 48000,
  "room_tone": {"start": 0.0, "end": 0.9},
  "lead_in_s": 0.40,
  "crossfade_ms": 25,
  "section_starts": [],
  "cuts": [
    {"start": 3.0, "end": 4.6, "kind": "major", "reason": "retake: speaker said 'let me redo that'"},
    {"start": 5.25, "end": 5.55, "kind": "micro", "reason": "doubled syllable"}
  ]
}
```

- `cuts[i].kind`: `major` for a retake, false start, spoken self-direction, or removed passage; `micro` for a filler, stutter, or doubled syllable inside a phrase. The kind selects the pause used across the join.
- `room_tone`: a window of clean background noise from the same recording, or `"auto"` (default) to use the quietest 2 s window in the first 10 minutes. Check an automatic choice with `vlog quiet`.
- `section_starts`: raw times of section openings; the island that starts within 1.2 s of one gets the section pause.
- `pacing` and `edges` are optional partial overrides, deep-merged over the defaults:

```json
{
  "pacing": {
    "keep_gap_s": {"period": 1.00, "comma": 0.75, "none": 0.60},
    "section_pause_s": 1.15,
    "section_match_window_s": 1.2,
    "after_micro_cut_s": {"period": 0.85, "comma": 0.55, "none": 0.08},
    "after_major_cut_s": {"period": 0.88, "comma": 0.58, "none": 0.45},
    "long_gap_s": {"period": [0.85, 0.95, 1.60], "comma": [0.58, 0.66, 1.30], "none": [0.40, 0.50, 1.10]},
    "tail_s": 0.80,
    "edge_quiet_margin_s": 0.06
  },
  "edges": {
    "pre_pad_s": 0.045,
    "post_pad_s": 0.075,
    "max_onset_extension_s": 0.105,
    "max_release_extension_s": 0.165,
    "energy_threshold_mean_sq": 2.5e-5,
    "energy_window_s": 0.015
  }
}
```

These defaults are the values a speaker approved after listening. `long_gap_s[kind]` is `[target, target_if_very_long, very_long_threshold]`.

### 3.3 Manifest (`vlog.manifest/1`)

Written by `vlog edit` (abridged; `islands` and `words` cover the whole output):

```json
{
  "schema": "vlog.manifest/1",
  "source_audio": "/path/to/project/audio/raw/take1.wav",
  "transcript": "/path/to/project/asr/raw.json",
  "output_wav": "/path/to/project/audio/edited.wav",
  "output_m4a": "/path/to/project/audio/edited.m4a",
  "sample_rate": 48000,
  "raw_duration_s": 10.0,
  "edited_duration_s": 4.78,
  "peak_linear": 0.3026,
  "loudness": {"integrated_lufs": -14.5, "loudness_range_lu": 2.1, "true_peak_dbfs": -10.4},
  "room_tone": {"start": 0.0, "end": 0.9, "source": "plan"},
  "pacing": {"keep_gap_s": {"period": 1.0, "comma": 0.75, "none": 0.6}},
  "cuts": [{"start": 3.0, "end": 4.6, "kind": "major", "reason": "retake: speaker said 'let me redo that'"}],
  "islands": [
    {"index": 0, "out_start": 0.375, "out_end": 1.745, "raw_start": 0.955, "raw_end": 2.325, "pause_after": 0.45,
     "word_raw_start": 1.0, "word_raw_end": 2.25, "text": "我们看那"}
  ],
  "dropped_islands": [],
  "warnings": [],
  "words": [
    {"text": "我", "punc": "", "start": 0.42, "end": 0.62, "raw_start": 1.0, "raw_end": 1.2}
  ]
}
```

Inside island `k`, `t_raw = raw_start + (t_out - out_start)`. `words[].start/end` are output times; `raw_start/raw_end` are the original times.

### 3.4 Verify report (`vlog.verify/1`)

Written by `vlog verify` (synthetic example: an edit that left a doubled syllable at a join):

```json
{
  "schema": "vlog.verify/1",
  "edited_media": "audio/edited.wav",
  "edited_duration_s": 4.78,
  "joins_checked": 2,
  "joins_flagged": 1,
  "expect_absent_hits": [],
  "clean": false,
  "joins": [
    {
      "out_time": 2.43,
      "raw_gap": [5.25, 5.55],
      "cut_reasons": ["doubled syllable"],
      "edited": "我们看那要要好完",
      "raw_before": "我们看那要",
      "raw_after": "好完",
      "issues": [{"type": "doubled_near_join", "detail": "要要"}],
      "status": "review"
    }
  ]
}
```

`clean` is true only when no join is flagged and no expected-absent phrase is found. `vlog verify --markdown` also writes a table for reading.

---

## 4. Core Algorithms

### 4.1 Rendering an edit (`edit.py`)

1. Decode the source to 48 kHz stereo float32 with ffmpeg; take the room-tone slice.
2. Drop every word whose midpoint lies inside a cut. Give zero-length aligner words 50 ms.
3. Group the kept words into islands. Start a new island when a cut lies between two words (`cut.start >= prev.start - 0.05` and `cut.end <= next.end + 0.05`), or when the raw gap exceeds `keep_gap_s` for the punctuation class of the previous word (`period` if it contains 。？！.?!, `comma` if it contains ，；：、,;:, else `none`). Gaps inside an island are kept exactly as recorded.
4. Refine each island's edges on the waveform: pad by `pre_pad_s`/`post_pad_s`, then keep extending in half-window steps while the mean square energy over `energy_window_s` stays at or above `energy_threshold_mean_sq`, up to `max_onset_extension_s` before the first word and `max_release_extension_s` after the last. All of this is clamped to the neighbouring islands' word times (with 20 ms margin) and to every cut that ends before the midpoint of the island's first word (or within 50 ms after its start) or starts after the midpoint of its last word (or within 50 ms before its end). Comparing against midpoints matters: when the aligner stretches a kept word over a filler or a repeated syllable, the cut starts inside that word's token span, and the island must stop at the cut. An island that the cuts reduce to less than 20 ms is dropped and listed in `dropped_islands`.
5. Assemble: `lead_in_s` of room tone, then each island, then a room-tone pad, joined with `crossfade_ms` equal-power crossfades (cos/sin quarter-period). The pause after island `k` is:
   - `section_pause_s` if the next island starts within `section_match_window_s` of a `section_starts` entry;
   - else `after_major_cut_s[class]` if a major cut lies between the last word of `k` and the first word of `k+1` (with 0.15 s tolerance, or between the midpoints of those two words);
   - else `after_micro_cut_s[class]` if only micro cuts lie there;
   - else (a stall longer than `keep_gap_s`) `long_gap_s[class]`, using the larger target when the raw gap exceeds the threshold.
   The pad length is `pause - edge_quiet_margin_s` plus the two crossfades, because the refined edges already carry some quiet. Pads are cut from the room tone at an offset that varies with the island index; the final island is followed by `tail_s` of room tone.
6. Write 16-bit PCM WAV, optionally AAC M4A at 256 kb/s, measure loudness with ffmpeg `ebur128=peak=true`, and write the manifest.
7. Report every cut edge whose 15 ms level is at or above `edges.warn_edge_db` (default -35 dBFS) in `warnings` (type `cut_edge_in_speech`). Removing a stutter often puts the end edge at the next syllable's onset, which is expected; other warnings usually mean the edge should move into a quiet run.

On the production it was extracted from (a 23 minute recording, 55 cuts) the renderer matches the original hand-written script sample for sample except at two joins, where the old script's edge padding reached into a cut: one imported 0.1 s of room tone, the other the tail of a filler that re-transcription had not caught.

### 4.2 Verifying an edit (`verify.py`)

Inputs: the manifest, the raw transcript, and a fresh transcript of the edited audio.

1. A join is a pair of consecutive islands with at least one cut between their words (`cut.start < next.word_raw_start` and `cut.end > prev.word_raw_end`; manifests without those fields fall back to the refined edges).
2. For each join, with `j` the end of the earlier island and `k` the start of the later one in the output: collect edited words starting in `[j - 2.2, k + 2.2)` and in `[j - 1.0, k + 1.0)`, plus raw words before and after the gap. Latin tokens are joined with spaces.
3. In the narrower window, flag fillers (default 呃, 嗯, um, uh, erm; CJK fillers by substring, Latin ones by whole word) and doubled CJK characters (`XX`) unless allow-listed (`--allow-double 看看`). Flagged joins get `status: "review"`.
4. Search the whole edited text for every `--expect-absent` phrase, ignoring case, punctuation and spacing.
5. `clean` = no review joins and no expected-absent hits.

Limits that matter in practice: a partial syllable left at a join may not be transcribed at all, so `clean` is necessary but not sufficient, and the human listen stays mandatory. Legitimate reduplications (看看, 常常) are flagged until allow-listed.

### 4.3 Subtitles (`subtitles.py`)

- Glossary: a JSON object mapping recognized text to the intended text, for example `{"P二": "PR", "扣的瑞维有": "code review"}`. Replacements are plain substring replacements on each cue's text, longest key first.
- Chunking: words are grouped into sentences (closed at 。？！.?!) and clauses (closed at ，；：、,;:). Clauses are packed into a cue while the cue fits `max_width` (measured after glossary replacement; CJK characters count 1, other visible characters 0.5, spaces 0.25). A clause wider than `max_width` is split into the fewest pieces that each fit, choosing all cuts together (near-equal widths, cuts pulled toward particles, clause openers and script changes, never inside a glossary key) rather than filling greedily, so a long clause does not leave a one-character orphan (a one-character clause between full cues can still stand alone). Cues never cross a sentence end. Latin words are separated by a space even after punctuation. Trailing ，。、；： and ASCII ,;: are dropped from the displayed text. ASR may also space Latin letters ("A B"), so add spaced forms to the glossary.
- Timing: a cue spans its first word's start to its last word's end, extended to at least 0.8 s, and always ends at or before the next cue's start. SRT times are written from integer milliseconds.
- `vlog subtitles` lists cues shorter than 1.3 s so they can be fixed by adjusting punctuation.

### 4.4 Timing between renders and the picture (`align.py`)

- `vlog offset reference other --at t1 t2 ...`: decodes a `--window` (default 30 s) of mono 8 kHz audio from both files at each point and takes the cross-correlation peak. Each point reports `offset_ms` (positive when `other` is late) and the normalised correlation; `aligned` is true when every offset is within `--tolerance-ms` (default 20) and every correlation exceeds 0.9. On the first production a direct avatar render measured 0 ms; a Video Agent render measured 0, -92 and -160 ms at 5, 500 and 1000 s.
- `vlog offset reference other --global [--points 5] [--window 8]`: for recordings that started far apart. Both files are decoded whole at 8 kHz mono and high-passed at 150 Hz (removing hum). A coarse search cross-correlates 10 ms log-energy envelopes over the whole overlap and keeps the three best peaks; each candidate is refined at `--points` positions spread over the overlap with GCC-PHAT on the audio, the best candidate is kept, and the points are placed again from the refined offset. A line (offset + drift) is fitted through the points. The summary reports `start_delta_s` (other start minus reference start at reference time 0, so `reference_time = other_time + start_delta_s + drift`), `drift_ms_per_min`, `confidence` (median GCC-PHAT peak sharpness), `coarse_confidence`, per-point `delta_s`, `residual_ms`, `correlation` (over 2 s at the aligned lag) and `peak_sharpness`, and `aligned` (confidence > 3, median correlation > 0.5, every residual within `--tolerance-ms`), plus a `reason` when not aligned. Two 20-minute files take about 1.3 s and 0.7 GB.
- `vlog anchors transcript --phrase NAME=PHRASE ... [--after s] [--until s]`: concatenates the words without spaces, finds each phrase's first occurrence whose first word starts inside the window, and returns that start time. Any missing phrase raises `KeyError` (exit 4), so a reworded line cannot silently move its picture beat.

### 4.5 Distribution clips (`clip.py`)

- Each `--segment START:END` (source seconds) becomes its own ffmpeg input (`-ss START -t LEN -i video`), so late segments do not decode the whole film. Picture: `setpts=PTS-STARTPTS,fps=<source rate as a rational, avg_frame_rate falling back to r_frame_rate>,settb=AVTB,format=yuv420p`; sound: `asetpts=PTS-STARTPTS,aresample=48000`, stereo.
- Segments are joined in order with `xfade=transition=fade` and `acrossfade` (`qsin` curves) of `--crossfade` seconds (default 0.3; `concat` when 0). Offsets come from `timeline()`: each join starts `crossfade` before the end of the running length. The audio is trimmed to the joined length (`body_s`), faded in at 0 and faded out so that the fade ends at `body_s`; only then does `--hold-end` add silence (`apad`) while the picture holds its last frame (`tpad=stop_mode=clone`). Optional `fade` to black with `--video-fade-out`. Output length = sum of segments - crossfades + hold (+ end card).
- End card (`--end-card`): a number is a time on the source clock, whose frame is extracted to a temporary PNG; anything else is an image path. The still is looped (`-loop 1 -framerate <source rate> -t <card + crossfade>`), scaled into the source size with letterboxing, and joined with `xfade=transition=fade` of `--end-card-crossfade` (default 0.5 s) at offset `body + hold - crossfade`, so the card is fully visible for `--end-card-duration` (default 2.5 s) and total = body + hold + card. The audio is padded with silence to the total (`apad=whole_dur`), so the card is silent. With `--srt`, a card time inside a cue gives an `end_card_inside_cue` warning; a card time after the end of the source raises `ValueError`. The summary reports `end_card` (`kind`, `t` or `path`, `duration_s`, `crossfade_s`, `starts_at_s`).
- Loudness: pass 1 runs the audio graph into `loudnorm=I:TP:LRA=11:print_format=json`; pass 2 renders with the measured values, `linear=true`, and a target LRA of `min(50, max(11, ceil(input_lra) + 1))`. `loudnorm` falls back to dynamic mode when the true peak after linear gain (`input_tp + (I - input_i)`) would exceed `TP`, or when the input LRA exceeds the target LRA; the command reports `normalization_type` and, if it is not linear, a `loudnorm_not_linear` warning whose `reasons` name the failed condition (`true_peak` or `lra`). Defaults: -16 LUFS, -1 dBTP.
- Encode: `libx264 -profile:v high -crf 16 -pix_fmt yuv420p`, AAC 192 kb/s 48 kHz stereo, `-movflags +faststart`. Only the two filter outputs are mapped, so the source's subtitle, data and attachment streams are never copied; `-map_metadata -1 -map_chapters -1` drop the container title, other tags and chapters. An output whose streams are not exactly `[video, audio]` gets an `extra_streams` warning. `faststart` in the summary is computed by walking the top-level MP4 boxes (`moov` before `mdat`).
- Edge checks: with `--srt`, every edge is either `inside_cue` (with the cue) or reported with the cue gap it sits in (`edge_inside_cue` warning). Independently, the 10 ms RMS envelope of the source is measured: the segment's speech level is its 90th percentile, and each edge's level is the loudest window within 0.1 s; a margin under 10 dB is an `edge_in_speech` warning. A segment whose p90 is within 6 dB of its median (`spread_db`) has no speech (a title card over music); its edges are not judged and an `edge_check_skipped` warning carries the spread. A segment that decodes to no audio raises `ValueError`. Output checks: `loudness_off_target` when the measured integrated loudness is more than 0.5 LU from `--lufs`, `true_peak_over` when the measured true peak exceeds `--true-peak` by more than 0.1 dB. Other warnings: `over_max_duration` (default 140 s; 0 disables), `duration_mismatch` (more than 0.15 s from the expected length), `not_faststart`.
- Stills: `<stem>_first.png`, `<stem>_last.png` (last decoded frame), and `<stem>_sheet.png` (`--sheet-frames` evenly spaced frames from first to last, 480 px wide, tiled 4 across). `--sheet-frames 0` skips all stills.

---

## 5. HeyGen (external, not wrapped)

v0.1 briefly contained `vlog heygen`, a standard-library client for the HeyGen v3 API. It was removed: an API key bills a separate pay-as-you-go wallet at about three times the per-minute price of subscription credits, while HeyGen's official CLI (`heygen`) can sign in with OAuth and bill subscription credits. The skill therefore points to the web UI and the official CLI (see `skills/vlog/SKILL.md`, "Avatar video with HeyGen"), and this package needs no credentials.

Observed in the first production: a 60 s render through `heygen video create` (`type: avatar`, Avatar III, 1080p) with OAuth cost 4 subscription credits and returned audio identical to the upload (0 ms offset). The speaker judged that direct render visibly worse than renders made through HeyGen's Video Agent with the same engine; the cause has not been established yet, so treat the direct path as untested for quality.

---

## 6. CLI Output Envelope and Error Handling

Every `vlog` command prints exactly one JSON document to `stdout`, including usage errors. Only `--help` and `--version` print plain text.

### Success envelope (exit code 0)

Real output of `vlog edit` on the synthetic demo:

```json
{
  "command": "edit",
  "ok": true,
  "data": {
    "output_wav": "/path/to/project/audio/edited.wav",
    "output_m4a": "/path/to/project/audio/edited.m4a",
    "raw_duration_s": 10.0,
    "edited_duration_s": 4.78,
    "peak_linear": 0.3026,
    "loudness": {"integrated_lufs": -14.5, "loudness_range_lu": 2.1, "true_peak_dbfs": -10.4},
    "manifest": "/path/to/project/edit/manifest.json",
    "cuts": 2,
    "islands": 4
  }
}
```

### Error envelope (non-zero exit code)

Error details are passed through, not summarized:

```json
{
  "command": "quiet",
  "ok": false,
  "error": {"type": "ToolError", "message": "ffmpeg could not decode not_audio.wav: ... Invalid data found when processing input", "details": null}
}
```

For ffmpeg failures (`ToolError`) the message carries ffmpeg's stderr. For other exceptions `details` carries a short traceback.

### Exit codes

| Code | Meaning | Examples |
| :--- | :--- | :--- |
| 0 | Success | Command completed. `vlog verify` also exits 0 when it finds problems; read `clean` and `joins_flagged`. |
| 2 | Usage error | Unknown subcommand, missing required flag |
| 3 | Missing dependency | ffmpeg or ffprobe not on PATH; `mlx-qwen3-asr` not installed |
| 4 | Bad input | Missing file, malformed JSON, invalid plan (a cut with start >= end, unknown kind, a room-tone window outside the recording or shorter than 0.2 s), nothing left to render, `vlog init` inside the repository |
| 5 | External tool failure | ffmpeg returned an error, including media it cannot decode |

Overlapping cuts are allowed; a word is dropped if its midpoint falls in any of them.

---

## 7. Testing Strategy

Testing is split into three tiers (detailed in `docs/test.md`):

1. **Offline tests (`pytest`)**: run on any machine with Python 3.12, numpy, ffmpeg and ffprobe. Audio is synthesized (tone bursts as syllables over a -62 dBFS noise floor), so a test can check which syllables survived an edit by the dominant frequency at each output time. HeyGen calls go through an injectable opener (`Client(opener=...)`) that serves canned responses. They cover the edit (cuts, kept pauses, shortened stalls, clamped edges, manifest time map, overrides), quiet runs, punctuation, utterances, verification flags, subtitles, the HeyGen request shapes and upload paths, and CLI envelopes and exit codes.
2. **Hardware- or credential-gated checks** (`vlog transcribe` on Apple Silicon) are manual for now; `docs/test.md` lists them.
3. **Production manual acceptance checklist**: Executed by the agent and human on real episodes.

---

## 8. Open Questions

1. **HeyGen render quality and duration through the official CLI**: the speaker judged a direct `heygen video create` render worse than a Video Agent render with the same engine; find out which settings differ. HeyGen's documentation also disagrees on the per-request audio cap (30 minutes on most pages, 10 minutes for audio input on one).
2. **HeyGen transparent background (`webm` alpha channel)**:
   `output_format: "webm"` provides an alpha channel only when the digital twin was trained with matting and only for single-scene requests. Whether a specific user's private digital twin supports matting is not exposed in `GET /v3/avatars/looks` metadata and must be tested per avatar look.
3. **v0.2 Timeline Schema (`vlog.timeline/1`)**:
   Exact coordinate system and transition primitives for `vlog compose` (side-panel split ratios, corner picture-in-picture geometry, and audio ducking attack/release curves) will be finalized in v0.2 after benchmarking `ffmpeg` filtergraph performance on 4K vs 1080p renders.
