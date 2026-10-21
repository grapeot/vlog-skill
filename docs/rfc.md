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
│   └── edited.m4a             # Rendered AAC edit for listening & HeyGen upload
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
                           HeyGen Web UI / vlog heygen
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
| `vlog_skill/project.py` | Implements `vlog init <project_dir>`. Creates the standard project directory hierarchy (`research`, `writing`, `audio/raw`, `asr`, `edit`, `avatar`, `subtitles`, `storyboard`, `broll`, `render`). Refuses to initialize inside the `vlog-skill` git working tree unless explicitly overridden in tests. |
| `vlog_skill/audio.py` | Thin subprocess wrapper around `ffmpeg` and `ffprobe`. Probes media streams (`ffprobe -of json`), decodes arbitrary input media to mono float32 `numpy` arrays at a target sample rate (`48000` Hz default), writes 16-bit/24-bit PCM WAV files, transcodes WAV to AAC M4A, and measures integrated loudness (`I`), loudness range (`LRA`), and true peak (`TP`) by parsing `ffmpeg -af ebur128=peak=true` output. |
| `vlog_skill/transcribe.py` | Implements `vlog transcribe <media> --out <json>`. If `<media>` is a video container, extracts a temporary WAV via `audio.py`. Dynamically imports `mlx_qwen3_asr` (raising exit code `3` if the optional `[asr]` extra is not installed), runs `Qwen3-ASR-1.7B` with `Qwen3-ForcedAligner-0.6B`, attaches punctuation marks to preceding word tokens, and writes `vlog.transcript/1`. |
| `vlog_skill/utterances.py` | Implements `vlog utterances <transcript.json>`. Groups consecutive words from `vlog.transcript/1` into utterances split where inter-word gaps exceed `--pause-s` (default `0.40` s) or at sentence-ending punctuation. Returns structured utterance records and formats a compact timing table. |
| `vlog_skill/quiet.py` | Implements `vlog quiet <audio> --start <s_float> --end <s_float> [--threshold-db <float>]`. Slices the waveform over `[start, end]`, computes a 10 ms non-overlapping RMS envelope in dBFS (`20 * log10(rms + 1e-12)`), and merges contiguous windows below `--threshold-db` (default `-45.0` dBFS) into quiet intervals `{start, end, duration, min_db}`. |
| `vlog_skill/edit.py` | Implements `vlog edit <edit_plan.json>`. Filters cut words, groups kept words into islands, refines island boundaries using local RMS energy clamped to cut and neighbor boundaries, inserts room-tone pauses according to the pacing table, joins segments with 25 ms raised-cosine crossfades, writes WAV and M4A outputs, measures loudness, and emits `vlog.manifest/1`. |
| `vlog_skill/verify.py` | Implements `vlog verify`. Reads `manifest.json` (which carries the cuts and islands), `raw.json`, and `edited.json`. Extracts text windows around every join that crosses a cut, flags fillers or doubled characters near joins as `"review"`, searches the entire edited transcript for `--expect-absent` phrases, and writes `vlog.verify/1` JSON and Markdown reports. |
| `vlog_skill/subtitles.py` | Implements `vlog subtitles <transcript.json> [--glossary <glossary.json>] --out <srt>`. Applies glossary replacements to each cue's text, splits cues at punctuation up to ~22 CJK characters per cue without crossing sentence boundaries, and writes UTF-8 `.srt`. |
| `vlog_skill/heygen.py` | Implements `vlog heygen` subcommands (`me`, `looks`, `upload`, `create`, `status`, `wait`, `download`) against `https://api.heygen.com` v3 using `urllib.request`. Reads `HEYGEN_API_KEY` from the environment or a local `.env` file. |
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
    {"index": 0, "out_start": 0.375, "out_end": 1.745, "raw_start": 0.955, "raw_end": 2.325, "pause_after": 0.45, "text": "我们看那"}
  ],
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
4. Refine each island's edges on the waveform: pad by `pre_pad_s`/`post_pad_s`, then keep extending in half-window steps while the mean square energy over `energy_window_s` stays at or above `energy_threshold_mean_sq`, up to `max_onset_extension_s` before the first word and `max_release_extension_s` after the last. All of this is clamped to the neighbouring islands' word times (with 20 ms margin) and to the edges of adjacent cuts, so padding never re-imports deleted audio.
5. Assemble: `lead_in_s` of room tone, then each island, then a room-tone pad, joined with `crossfade_ms` equal-power crossfades (cos/sin quarter-period). The pause after island `k` is:
   - `section_pause_s` if the next island starts within `section_match_window_s` of a `section_starts` entry;
   - else `after_major_cut_s[class]` if a major cut lies between the last word of `k` and the first word of `k+1` (with 0.15 s tolerance);
   - else `after_micro_cut_s[class]` if only micro cuts lie there;
   - else (a stall longer than `keep_gap_s`) `long_gap_s[class]`, using the larger target when the raw gap exceeds the threshold.
   The pad length is `pause - edge_quiet_margin_s` plus the two crossfades, because the refined edges already carry some quiet. Pads are cut from the room tone at an offset that varies with the island index; the final island is followed by `tail_s` of room tone.
6. Write 16-bit PCM WAV, optionally AAC M4A at 256 kb/s, measure loudness with ffmpeg `ebur128=peak=true`, and write the manifest.

The renderer reproduces, sample for sample, the hand-written script used in the production it was extracted from (verified on a 23 minute recording with 55 cuts).

### 4.2 Verifying an edit (`verify.py`)

Inputs: the manifest, the raw transcript, and a fresh transcript of the edited audio.

1. A join is a pair of consecutive islands with at least one cut between them (`cut.start < next.raw_start` and `cut.end > prev.raw_end`).
2. For each join at output time `j`: collect edited words starting in `[j - 2.2, j + 2.2)`, raw words before and after the gap, and edited words within `±1.0 s`.
3. Within `±1.0 s`, flag fillers (default 呃, 嗯, um, uh, erm; CJK fillers by substring, Latin ones by whole word) and doubled CJK characters (`XX`) unless allow-listed (`--allow-double 看看`). Flagged joins get `status: "review"`.
4. Search the whole edited text for every `--expect-absent` phrase.
5. `clean` = no review joins and no expected-absent hits.

Limits that matter in practice: a partial syllable left at a join may not be transcribed at all, so `clean` is necessary but not sufficient, and the human listen stays mandatory. Legitimate reduplications (看看, 常常) are flagged until allow-listed.

### 4.3 Subtitles (`subtitles.py`)

- Glossary: a JSON object mapping recognized text to the intended text, for example `{"P二": "PR", "扣的瑞维有": "code review"}`. Replacements are plain substring replacements on each cue's text, longest key first.
- Chunking: words are appended to a cue until adding the next word would exceed `max_width` (CJK characters count 1, other visible characters 0.5); a cue is closed at every sentence end and at a clause end once it is at least 60% full. Trailing ，。、；： are dropped from the displayed text.
- Timing: a cue spans its first word's start to its last word's end, extended to at least 0.8 s but never past the next cue. SRT times are written from integer milliseconds.
- `vlog subtitles` lists cues shorter than 1.3 s so they can be fixed by adjusting punctuation.

---

## 5. HeyGen API v3 Client (`vlog_skill/heygen.py`)

**Implementation Status**: Implemented against HeyGen API v3 documentation researched on 2026-10-20; not yet exercised with a live API key. HeyGen v1 and v2 APIs shut down on 2026-10-31; `vlog heygen` targets v3 exclusively.

### 5.1 Authentication and Billing Constraints

- Base URL: `https://api.heygen.com`
- Header: `X-Api-Key: <HEYGEN_API_KEY>` (read from the `HEYGEN_API_KEY` environment variable or a `.env` file given by `--env-file`, default `./.env`; never echoed in logs or error payloads).
- **Billing warning**: API calls draw from a separate pay-as-you-go API wallet, not a HeyGen web subscription. An 18-minute digital-twin render on the newest engine costs on the order of $100 USD via the API versus significantly less in web-plan credits. Uploading `audio/edited.m4a` via the HeyGen web UI and downloading `avatar/avatar.mp4` remains a first-class supported workflow.

### 5.2 Endpoints and Subcommands

1. `vlog heygen me`:
   Queries account/quota status to verify the API key and remaining balance.
2. `vlog heygen looks`:
   `GET /v3/avatars/looks?avatar_type=digital_twin&ownership=private`
   Returns each look's `id` (used as `avatar_id`), `name`, `status`, and `supported_api_engines`.
3. `vlog heygen upload <audio>`:
   - If file size `<= 32 * 1024 * 1024` bytes (32 MB): simple multipart upload `POST /v3/assets` with field `file` (`audio/mpeg` or `audio/wav`).
   - If file size `> 32` MB: 3-step direct upload:
     1. `POST /v3/assets/direct-uploads` with JSON `{"filename": name, "content_type": mime, "size_bytes": size}` -> returns `{asset_id, upload_url, upload_headers}`.
     2. `PUT <upload_url>` with the raw file bytes and `upload_headers` passed verbatim.
     3. `POST /v3/assets/{asset_id}/complete` with body `{}`.
   - Returns `asset_id` (asset IDs do not expire).
4. `vlog heygen create --avatar-id <id> --audio-asset-id <id> [--engine <type>] [--resolution <res>] [--aspect-ratio <ratio>] [--format mp4|webm] [--title <str>] [--idempotency-key <key>]`:
   `POST /v3/videos` with body:
   ```json
   {
     "type": "avatar",
     "avatar_id": "<look_id>",
     "audio_asset_id": "<asset_id>",
     "engine": {"type": "avatar_iv"},
     "resolution": "1080p",
     "aspect_ratio": "16:9",
     "output_format": "mp4",
     "title": "episode-01"
   }
   ```
   Sends `Idempotency-Key` header when provided (HeyGen replays the original response for 24 hours).
5. `vlog heygen status <video_id>`:
   `GET /v3/videos/{video_id}`. Returns `status` (`pending`, `processing`, `completed`, `failed`, or other non-terminal values like `waiting`), `video_url`, `duration`, `failure_code`, and `failure_message`.
6. `vlog heygen wait <video_id> [--timeout 7200] [--interval 30]`:
   Polls `GET /v3/videos/{video_id}` every `--interval` seconds. Treats `completed` as success, `failed` as exit code `5` (including `failure_code` and `failure_message`), and any other status (`pending`, `processing`, `waiting`, etc.) as still running until `--timeout` expires.
7. `vlog heygen download <video_id> --out <path>`:
   Calls `GET /v3/videos/{video_id}` immediately before downloading to obtain a fresh presigned `video_url`, then streams the file to `<path>`.

---

## 6. CLI Output Envelope and Error Handling

Every `vlog` command prints exactly one JSON document to `stdout`. Diagnostic progress, if any, goes to `stderr`.

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

Upstream details are passed through, not summarized. For HeyGen, `details` carries the HTTP status, the raw response body, and the URL:

```json
{
  "command": "heygen status",
  "ok": false,
  "error": {
    "type": "UpstreamError",
    "message": "HeyGen request failed (403) for https://api.heygen.com/v3/videos/v1: {\"error\":{\"code\":\"api_key_required\"}}",
    "details": {"status": 403, "body": "{\"error\":{\"code\":\"api_key_required\"}}", "url": "https://api.heygen.com/v3/videos/v1"}
  }
}
```

For ffmpeg failures (`ToolError`) the message carries ffmpeg's stderr. For other exceptions `details` carries a short traceback.

### Exit codes

| Code | Meaning | Examples |
| :--- | :--- | :--- |
| 0 | Success | Command completed. `vlog verify` also exits 0 when it finds problems; read `clean` and `joins_flagged`. |
| 2 | Usage error | Unknown subcommand, missing required flag |
| 3 | Missing dependency or credential | ffmpeg or ffprobe not on PATH; `mlx-qwen3-asr` not installed; `HEYGEN_API_KEY` not set |
| 4 | Bad input | Missing or malformed file, invalid plan (a cut with start >= end, unknown kind), nothing left to render |
| 5 | Upstream failure | HeyGen HTTP 4xx/5xx or network error, a render that ended in `failed` (`vlog heygen wait`), ffmpeg returned an error |

Overlapping cuts are allowed; a word is dropped if its midpoint falls in any of them.

---

## 7. Testing Strategy

Testing is split into three tiers (detailed in `docs/test.md`):

1. **Offline tests (`pytest`)**: run on any machine with Python 3.12, numpy, ffmpeg and ffprobe. Audio is synthesized (tone bursts as syllables over a -62 dBFS noise floor), so a test can check which syllables survived an edit by the dominant frequency at each output time. HeyGen calls go through an injectable opener (`Client(opener=...)`) that serves canned responses. They cover the edit (cuts, kept pauses, shortened stalls, clamped edges, manifest time map, overrides), quiet runs, punctuation, utterances, verification flags, subtitles, the HeyGen request shapes and upload paths, and CLI envelopes and exit codes.
2. **Hardware- or credential-gated checks** (`vlog transcribe` on Apple Silicon, `vlog heygen` with a funded key) are manual for now; `docs/test.md` lists them.
3. **Production manual acceptance checklist**: Executed by the agent and human on real episodes.

---

## 8. Open Questions

1. **HeyGen single-request audio duration cap**:
   HeyGen v3 documentation states a 30-minute maximum video duration on general pages, but one audio-input page specifies a 10-minute cap for uploaded audio assets. Until verified against a live account, audio longer than 10 minutes should be split at a long section pause into `<= 10` minute segments, rendered separately, and joined locally.
2. **HeyGen transparent background (`webm` alpha channel)**:
   `output_format: "webm"` provides an alpha channel only when the digital twin was trained with matting and only for single-scene requests. Whether a specific user's private digital twin supports matting is not exposed in `GET /v3/avatars/looks` metadata and must be tested per avatar look.
3. **v0.2 Timeline Schema (`vlog.timeline/1`)**:
   Exact coordinate system and transition primitives for `vlog compose` (side-panel split ratios, corner picture-in-picture geometry, and audio ducking attack/release curves) will be finalized in v0.2 after benchmarking `ffmpeg` filtergraph performance on 4K vs 1080p renders.
