---
name: vlog
description: Produce a narrated talking-head explainer video end to end from a topic or raw idea with a human in the loop. Use this skill when researching a topic, drafting a spoken script, editing a human voice recording via word-level ASR and waveform silence analysis, verifying audio joins, generating a lip-synced avatar video with HeyGen, or building a transcript-keyed storyboard and B-roll plan with the vlog CLI.
---

# vlog Skill

## Goal and Scope

Produce a rendered explainer video in which the speaker's own digital-twin avatar delivers the speaker's own edited voice-over, composited with B-roll (procedural animation, illustrations, screen recordings), subtitles, and a ducked music bed.

### Validation Status

| Pipeline Area | Status | Notes |
| :--- | :--- | :--- |
| Stages 1–9 (research, script, recording, transcription, edit, verify, listening) | Exercised in one production | A ~17-minute Chinese technical explainer; `vlog edit` reproduces that production's edit sample for sample |
| Stage 10, HeyGen web UI | In use in that production | The avatar video was being generated from the edited audio when v0.1 was written |
| Stage 10, `vlog heygen` API client | Implemented, not yet exercised with a real key | Built against the HeyGen API v3 documentation (2026-10-20) |
| Stages 11–13 (avatar re-transcription, storyboard, B-roll) | Designed, not yet exercised | The storyboard approach (composition modes keyed to spoken phrases) comes from the first production's plan |
| `vlog subtitles` | Implemented, tested on synthetic data | Punctuation-aware SRT with a glossary |
| Stage 14 (compose and render) | Planned | Not implemented in v0.1 |
| Stage 15 (final QA) | Designed, not yet exercised | |

### Boundaries and Responsibilities

- **Agent responsibilities**: Research and build the source contract; propose outline and draft script; run ASR transcription; analyze pauses and quiet windows; author `edit/edit_plan.json`; render and verify edited audio; generate or coordinate avatar video; re-transcribe avatar audio as the master clock; write the storyboard and subtitle glossary; generate B-roll assets; run final QA checks.
- **Human responsibilities**: Decide thesis and outline; approve script; record raw voice-over; listen to edited audio; generate or approve avatar video (and approve API spend if using `vlog heygen`); review final render.
- **Hard constraints**:
  1. **The agent cannot hear audio.** It measures loudness, energy envelopes, and transcripts. At every audio checkpoint, the agent must state plainly that a human must listen to judge delivery, pacing, and tone.
  2. **The agent never publishes anything.** Uploading or publishing to external video platforms is strictly out of scope.
  3. **No private data in version control.** Never commit audio recordings, transcripts, avatar videos, rendered outputs, API keys, personal names, or machine-specific paths.
- **Out of scope**: Platform publishing, text-to-video generation, text-to-speech (TTS) voice cloning (the voice is always the human's own recording), and GUI non-linear editors (NLEs).

---

## Human-in-the-Loop Checkpoints

Execution must pause for explicit human input or approval at five checkpoints:

1. **Checkpoint 1 — Thesis and Outline (Stage 2)**: Human approves target audience, single thesis, and section budget in `writing/brief.md`.
2. **Checkpoint 2 — Script Approval and Voice Recording (Stages 3–4)**: Human approves `writing/script.md` and records `audio/raw/<take>.m4a`.
3. **Checkpoint 3 — Edited Audio Listening (Stage 9)**: Agent reports measured duration, integrated LUFS, true peak, and `vlog verify` results, states that it cannot judge delivery by ear, and waits for the human to listen to `audio/edited.m4a`.
4. **Checkpoint 4 — Avatar Video Generation (Stage 10)**: Human either runs the render in the HeyGen web UI or approves pay-as-you-go API wallet expenditure for `vlog heygen`.
5. **Checkpoint 5 — Final Render Review (Stage 15)**: Human reviews the final video alongside the QA report.

---

## Pipeline Stages

Stage order is strict only where a stage consumes a previous stage's artifact.

### Stage 1: Research
- **Goal**: Collect verified facts, primary sources, and claim strengths, separating sourced facts from the author's own judgments.
- **Artifact**: `research/source_contract.md`
- **Acceptance Criteria**:
  1. `research/source_contract.md` exists and separates sourced claims from author judgments under distinct headings.
  2. Every quantitative figure, date, mechanism, and attributed claim that later appears in `writing/script.md` or the kept audio transcript traces to a specific entry in `research/source_contract.md` with a URL or citation and a claim-strength label.

### Stage 2: Thesis and Outline (Checkpoint 1)
- **Goal**: Agree with the human on audience, core thesis, and section-by-section length budget.
- **Artifact**: `writing/brief.md`
- **Acceptance Criteria**:
  1. `writing/brief.md` defines the target audience, a one-sentence thesis, the speaker's measured speaking rate (characters or words per minute), and a section outline whose budgeted durations sum to the target video length.
  2. The human has explicitly approved `writing/brief.md`.
- **Advice**: Propose one sharp thesis. When the topic addresses a problem every target viewer already experiences, open directly on the problem itself rather than on a framing anecdote.

### Stage 3: Narration Script
- **Goal**: Write a spoken-style narration script budgeted to the speaker's real speaking rate and verified against fact drift and cold-reader confusion.
- **Artifact**: `writing/script.md`
- **Acceptance Criteria**:
  1. Every paragraph has a stable sequential ID (`P01`, `P02`, ...).
  2. Length is budgeted using the speaker's measured speaking rate (obtained by timing at least 20 seconds of the speaker's natural speech and counting characters or words per minute), never a generic default rate.
  3. **Fact-drift check (separate agent context)**: Comparing `writing/script.md` against `research/source_contract.md` finds zero uncontracted numbers, invented mechanisms, or unsupported absolutes.
  4. **Cold-read check (independent agent context seeing only `writing/script.md`)**: The cold reader accurately restates the thesis and flags zero undefined terms or logic jumps. Iterate until the cold read passes.

### Stage 4: Voice Recording (Checkpoint 2)
- **Goal**: Record the human speaker reading the script in one continuous session.
- **Artifact**: `audio/raw/take1.m4a` (or `.wav`)
- **Acceptance Criteria**:
  1. Audio file exists under `audio/raw/` and `ffprobe` reports a valid audio stream with duration > 0.
- **Advice**: Instruct the speaker to record one continuous file using an external microphone if available. Going off-script and speaking retakes or editing instructions aloud (for example, "let me redo that" or "this part should be cut") are expected and handled in Stage 6.

### Stage 5: Raw Transcription
- **Goal**: Generate a word-level timestamped transcript of the raw recording.
- **Artifact**: `asr/raw.json`
- **Acceptance Criteria**:
  1. `vlog transcribe audio/raw/take1.m4a --out asr/raw.json` exits with code 0.
  2. `asr/raw.json` contains non-empty `words` with `text`, `start`, and `end` fields spanning the recording.

### Stage 6: Edit Decisions
- **Goal**: Produce a complete cut plan that removes retakes, spoken self-directions, fillers, stutters, and off-script factual errors, with every cut boundary placed inside a measured quiet gap on the waveform.
- **Artifact**: `edit/edit_plan.json`
- **Acceptance Criteria**:
  1. `edit/edit_plan.json` validates against the edit plan schema. Every cut includes `start`, `end`, `kind` (`"major"` or `"micro"`), and a human-readable `reason`.
  2. Every spoken self-direction, false start, retake, filler, and repeated syllable found in `asr/raw.json` and `vlog utterances asr/raw.json` is covered by a cut.
  3. **Speech fact-check**: The kept transcript (what the speaker actually said, including off-script remarks) is checked against `research/source_contract.md`. Any off-script claim that contradicts or goes beyond the contract—such as an invented technical mechanism, a misattributed behavior, an unsupported absolute ("never"), or a relative date that will go stale—is either cut or flagged for the human.
  4. **Waveform-snapped boundaries**: Every cut `start` and `end` lies inside a quiet interval verified with `vlog quiet <source_audio> --start <t0> --end <t1>`, never copied blindly from forced-aligner token boundaries.
  5. `room_tone` is a 1.5–2.5 s window of clean background noise checked with `vlog quiet` (no breaths, clicks, or speech), or `"auto"`, in which case the window chosen (reported in the manifest as `room_tone`) is checked the same way.
- **Advice**:
  - Read spoken self-directions carefully before cutting them; they contain explicit instructions from the speaker.
  - When a word to delete has no quiet gap on one side, expand the cut to delete a slightly larger surrounding phrase that has quiet gaps on both sides and leaves a grammatical sentence.
  - Preserve the speaker-approved pacing defaults in `edit/edit_plan.json`: keep natural pauses untouched, shorten only stalls exceeding the thresholds, and refill shortened pauses with room tone rather than digital silence.

### Stage 7: Render the Edit
- **Goal**: Render the edited voice-over with equal-power crossfades and room-tone pads, and record the exact raw-to-output time mapping and loudness metrics.
- **Artifacts**: `audio/edited.wav`, `audio/edited.m4a`, `edit/manifest.json`
- **Acceptance Criteria**:
  1. `vlog edit edit/edit_plan.json` exits with code 0 and prints a JSON summary containing `edited_duration_s` and `loudness` (`integrated_lufs`, `true_peak_dbfs`).
  2. `audio/edited.wav`, `audio/edited.m4a`, and `edit/manifest.json` exist on disk.
  3. Every kept audio island in `edit/manifest.json` has `raw_start`, `raw_end`, `out_start`, and `out_end`, allowing any timestamp in the edited audio to map back to the raw recording.
  4. Every entry in the summary's `warnings` (`cut_edge_in_speech`) has been looked at: either the edge was moved into a quiet run, or it is a stutter removal whose end edge sits on the next syllable's onset. `dropped_islands` is empty or explained.

### Stage 8: Verify the Edit (Mandatory Loop with Stages 6–7)
- **Goal**: Re-transcribe the rendered audio and verify every join and deleted phrase to catch clipped syllables or residual fillers left by aligner inaccuracy.
- **Artifacts**: `asr/edited.json`, `edit/verify_report.json`, `edit/verify_report.md`
- **Acceptance Criteria**:
  1. `vlog transcribe audio/edited.wav --out asr/edited.json` exits with code 0.
  2. `vlog verify --manifest edit/manifest.json --raw asr/raw.json --edited asr/edited.json --out edit/verify_report.json --markdown edit/verify_report.md` runs, with one `--expect-absent` for each phrase that was cut on purpose (self-directions, wrong claims, retakes).
  3. `expect_absent_hits` is empty.
  4. Every join is `ok`, or its `review` flag has a written explanation checked against `asr/edited.json` and the `vlog quiet` envelope (legitimate doubled characters can be allow-listed with `--allow-double`). An actual defect (doubled syllable, residual filler, clipped consonant) means adjusting `edit/edit_plan.json` and repeating Stages 6–8.
  5. A clean report is necessary, not sufficient: a partial syllable at a join may not be transcribed at all. Stage 9 still applies.

### Stage 9: Human Listening Checkpoint (Checkpoint 3)
- **Goal**: Deliver measured metrics and verification results so the human can listen to and approve the edited audio.
- **Artifact**: Written status report to the human referencing `audio/edited.m4a`, `edit/manifest.json`, and `edit/verify_report.md`.
- **Acceptance Criteria**:
  1. Report includes the measured `edited_duration_s`, `loudness.integrated_lufs`, and `loudness.true_peak_dbfs` read from `edit/manifest.json` (never projected or estimated numbers).
  2. If `edited_duration_s` exceeds the target in `writing/brief.md`, report the overrun explicitly rather than silently cutting substantive content.
  3. Report states explicitly that the agent cannot hear audio and that the human must listen to verify pacing and delivery.
  4. Human approves the edited audio before Stage 10 proceeds.

### Stage 10: Avatar Video Generation (Checkpoint 4)
- **Goal**: Generate a talking-head video of the speaker's digital twin driven by `audio/edited.wav` or `audio/edited.m4a`.
- **Artifact**: `avatar/avatar.mp4`
- **Acceptance Criteria**:
  1. `avatar/avatar.mp4` exists and `ffprobe` confirms valid video and audio streams whose duration matches `audio/edited.wav` within 0.2 s.

### Stage 11: Re-transcribe Avatar Video (Master Clock)
- **Goal**: Transcribe the audio track of `avatar/avatar.mp4` to serve as the timing clock for the storyboard, B-roll, and subtitles.
- **Artifact**: `asr/avatar.json`
- **Acceptance Criteria**:
  1. `vlog transcribe avatar/avatar.mp4 --out asr/avatar.json` exits with code 0.
  2. `asr/avatar.json` spans the full duration of `avatar/avatar.mp4`.

### Stage 12: Storyboard and Subtitles
- **Goal**: Design the visual composition timeline keyed to phrases in `asr/avatar.json` and generate corrected SRT subtitles.
- **Artifacts**: `storyboard/storyboard.md`, `subtitles/glossary.json`, `subtitles/subtitles.srt`
- **Acceptance Criteria**:
  1. Every segment in `storyboard/storyboard.md` is anchored to exact phrases and timestamps from `asr/avatar.json` (never from `writing/script.md`, which the speaker may have departed from).
  2. Every segment specifies:
     - Composition mode: `avatar_full`, `avatar_side_panel`, `avatar_corner`, or `broll_only`
     - B-roll asset description or path
     - Anchor phrase where each visual event or transition lands
     - Sound effects (if any)
  3. `subtitles/glossary.json` maps ASR-misrecognized technical terms (for example, English product names or acronyms inside Chinese speech) to their canonical spellings.
  4. `vlog subtitles asr/avatar.json --glossary subtitles/glossary.json --out subtitles/subtitles.srt` produces an SRT file where cues split at punctuation, never cross a sentence end, and contain at most ~22 CJK characters per cue.
- **Advice**: Keep any single `avatar_full` stretch short and give the viewer's eye structured visual information to read at every beat.

### Stage 13: B-roll Production
- **Goal**: Produce all animations, illustrations, screen recordings, and music tracks required by `storyboard/storyboard.md`.
- **Artifacts**: Files under `broll/` and `audio/music/`
- **Acceptance Criteria**:
  1. Every B-roll asset referenced in `storyboard/storyboard.md` exists on disk.
  2. Generated illustrations follow one consistent visual style across the video.
  3. Procedural frame sequences and music beds are produced using the sibling skill at `https://github.com/grapeot/opus-video-audio-skill`.

### Stage 14: Compose and Render (Planned — Not Implemented in v0.1)
- **Goal**: Composite the avatar video, B-roll overlays, burned-in and muxed subtitles, sound effects, and ducked music bed into a final video normalized to -16 LUFS integrated loudness.
- **Artifacts**: `render/timeline.json`, `render/final.mp4`
- **Acceptance Criteria**:
  1. `render/final.mp4` exists, `ffmpeg` `ebur128` integrated loudness is `-16.0 +/- 0.5` LUFS, subtitles are both burned in and muxed as a stream, and audio/video stream durations match.

### Stage 15: Final QA (Checkpoint 5)
- **Goal**: Verify the final render for visual defects, sync drift, and audio truncation before human sign-off.
- **Artifacts**: `qa/contact_sheet.png`, `asr/final.json`, `qa/qa_report.md`
- **Acceptance Criteria**:
  1. Contact sheets sampled across `render/final.mp4` show no unintended black frames or layout clipping.
  2. `vlog transcribe render/final.mp4 --out asr/final.json` matches the expected spoken content without truncation at start or end.
  3. `ffprobe` confirms matching durations across video, audio, and subtitle streams.

---

## Project Layout

Running `vlog init /path/to/project` creates the workspace outside the code repository:

```text
/path/to/project/
├── research/
│   └── source_contract.md
├── writing/
│   ├── brief.md
│   └── script.md
├── audio/
│   ├── raw/
│   ├── edited.wav
│   ├── edited.m4a
│   └── music/
├── asr/
│   ├── raw.json
│   ├── edited.json
│   ├── avatar.json
│   └── final.json
├── edit/
│   ├── edit_plan.json
│   ├── manifest.json
│   ├── verify_report.json
│   └── verify_report.md
├── avatar/
│   └── avatar.mp4
├── storyboard/
│   └── storyboard.md
├── subtitles/
│   ├── glossary.json
│   └── subtitles.srt
├── broll/
├── render/
└── qa/
```

---

## CLI Reference

Every `vlog` command prints a single JSON summary object to `stdout` and passes upstream errors through with raw details (HTTP status code, response body, exception type, and message).

| Purpose | Command | Status |
| :--- | :--- | :--- |
| Initialize workspace | `vlog init /path/to/project` | Implemented (v0.1) |
| Word-level ASR transcription | `vlog transcribe <media> --out <json>` | Implemented (v0.1, requires `[asr]` on Apple Silicon) |
| Pause-split utterance table | `vlog utterances <transcript.json>` | Implemented (v0.1) |
| Find waveform quiet gaps | `vlog quiet <audio> --start <s0> --end <s1> [--threshold-db <db>]` | Implemented (v0.1) |
| Render edited audio & manifest | `vlog edit <edit_plan.json>` | Implemented (v0.1) |
| Audit joins & absent phrases | `vlog verify --manifest <manifest.json> --raw <raw.json> --edited <edited.json> --out <report.json> [--markdown <report.md>] [--expect-absent <phrase> ...] [--allow-double <XX> ...]` | Implemented (v0.1) |
| Generate SRT with glossary | `vlog subtitles <transcript.json> --glossary <glossary.json> --out <srt>` | Implemented (v0.1) |
| Check HeyGen API key/balance | `vlog heygen me` | Implemented, untested with real key |
| List private digital-twin looks | `vlog heygen looks` | Implemented, untested with real key |
| Upload audio asset to HeyGen | `vlog heygen upload <audio>` | Implemented, untested with real key |
| Create avatar render job | `vlog heygen create --avatar-id <id> --audio-asset-id <id> [--engine <type>] [--resolution <res>] [--aspect-ratio <ratio>] [--format mp4\|webm] [--title <title>] [--idempotency-key <key>]` | Implemented, untested with real key |
| Poll render status once | `vlog heygen status <video_id>` | Implemented, untested with real key |
| Wait for render completion | `vlog heygen wait <video_id> [--timeout <s>] [--interval <s>]` | Implemented, untested with real key |
| Download completed avatar video | `vlog heygen download <video_id> --out <path>` | Implemented, untested with real key |

---

## Schemas

Full specifications with examples are in `docs/rfc.md` section 3. The fields an agent reads most:

- `asr/*.json` (`vlog.transcript/1`): `words[]` with `text`, `start`, `end`, `punc` (the punctuation that follows the word; pacing and subtitles depend on it). For Chinese, one word per character.
- `edit/edit_plan.json` (`vlog.edit_plan/1`): `source_audio`, `transcript`, `output_wav`, `output_m4a`, `manifest` (relative to the plan file), `room_tone` (`{"start", "end"}` or `"auto"`), `section_starts`, and `cuts[]` with `start`, `end`, `kind` (`major` or `micro`), `reason`. Optional `pacing` and `edges` overrides are deep-merged over the speaker-approved defaults; leave them out unless the speaker asks for a different rhythm.
- `edit/manifest.json` (`vlog.manifest/1`): `edited_duration_s`, `loudness` (`integrated_lufs`, `true_peak_dbfs`), `room_tone`, `cuts`, `islands[]` (`raw_start`, `raw_end`, `out_start`, `out_end`, `pause_after`, `text`), and `words[]` with both output and raw times.
- `edit/verify_report.json` (`vlog.verify/1`): `clean`, `joins_checked`, `joins_flagged`, `expect_absent_hits`, and `joins[]` with `out_time`, `edited`, `raw_before`, `raw_after`, `issues[]`, `status` (`ok` or `review`).

Minimal edit plan:

```json
{
  "schema": "vlog.edit_plan/1",
  "source_audio": "../audio/raw/take1.m4a",
  "transcript": "../asr/raw.json",
  "output_wav": "../audio/edited.wav",
  "output_m4a": "../audio/edited.m4a",
  "manifest": "manifest.json",
  "room_tone": {"start": 42.0, "end": 44.0},
  "section_starts": [12.0, 50.0],
  "cuts": [
    {"start": 40.10, "end": 50.00, "kind": "major", "reason": "false start plus a 6.5 s pause"},
    {"start": 121.30, "end": 121.55, "kind": "micro", "reason": "doubled word"},
    {"start": 200.00, "end": 209.50, "kind": "major", "reason": "claim not supported by the sources"}
  ]
}
```

---

## HeyGen Avatar Generation Path

### Option A: HeyGen web UI (in use in the first production)
1. Upload `audio/edited.m4a` or `audio/edited.wav` in the HeyGen web interface.
2. Select the speaker's private digital twin look and start the render (uses web subscription credits, which are significantly cheaper for long videos than pay-as-you-go API credits).
3. Download the finished MP4 to `avatar/avatar.mp4` and proceed to Stage 11.

### Option B: `vlog heygen` CLI (Implemented Against v3 API; Untested with Real Key)
- **API Version & Auth**: Uses HeyGen API v3 only (`https://api.heygen.com`, header `X-Api-Key` read from `HEYGEN_API_KEY` environment variable or a gitignored `.env`; never printed). HeyGen v1 and v2 shut down on 2026-10-31.
- **Billing Warning**: API usage bills from a separate pay-as-you-go wallet, not the web subscription. An 18-minute digital-twin render on the newest engine costs on the order of $100 USD via the API. Always check current prices in HeyGen's documentation and get human confirmation before starting a long API render.
- **Duration Cap**: HeyGen documentation states a 30-minute cap on most pages but a 10-minute cap for audio input on one page. Until verified with a key, split edited audio longer than 10 minutes at a long pause into segments under 10 minutes, render each separately, and concatenate locally with `ffmpeg`.
- **Workflow**:
  1. Verify credentials: `vlog heygen me`
  2. Find the digital twin's look ID: `vlog heygen looks` (queries `GET /v3/avatars/looks?avatar_type=digital_twin&ownership=private`; use the look `id` as `--avatar-id` after checking `status` and `supported_api_engines`).
  3. Upload audio: `vlog heygen upload audio/edited.wav` (WAV or MP3 only; an M4A is rejected, convert it first; uses `POST /v3/assets` multipart for files <= 32 MB, or 3-step direct upload via `POST /v3/assets/direct-uploads`, `PUT` with verbatim `upload_headers`, and `POST /v3/assets/{asset_id}/complete` for larger files; `asset_id` does not expire).
  4. Submit job: `vlog heygen create --avatar-id <look_id> --audio-asset-id <asset_id> --engine avatar_iv --resolution 1080p --aspect-ratio 16:9 --format mp4 --idempotency-key <uuid>` (sends `POST /v3/videos` with `type: "avatar"`; true 4K is supported only on Avatar III with a 4K-trained twin; `webm` provides an alpha channel only for a matting-trained twin on single-scene requests; `Idempotency-Key` replays the original response for 24 hours).
  5. Wait and download: `vlog heygen wait <video_id> --timeout 7200 --interval 30` then `vlog heygen download <video_id> --out avatar/avatar.mp4` (polls `GET /v3/videos/{video_id}`; treats unknown non-terminal statuses such as `"waiting"` as running; fetches a fresh presigned `video_url` before downloading).
- **Alternative Official Tooling**: HeyGen also provides an official CLI (`heygen video create --wait`, `heygen video download`) and an MCP server.

---

## Degraded Cases

| Condition | Detection | Fallback Action |
| :--- | :--- | :--- |
| **No Apple Silicon / `mlx-qwen3-asr` unavailable** | `vlog transcribe` fails with import or platform error | Run `vlog transcribe` on an Apple Silicon machine and copy `asr/*.json` into the project, or supply an external word-level transcript formatted to the `transcript.json` schema. All other commands (`utterances`, `quiet`, `edit`, `verify`, `subtitles`, `heygen`) run on any OS with Python 3.12 and `ffmpeg`. |
| **No `HEYGEN_API_KEY` or API budget constraint** | `HEYGEN_API_KEY` unset or human declines API wallet cost | Pause at Stage 10 and instruct the human to upload `audio/edited.m4a` in the HeyGen web UI and save the output to `avatar/avatar.mp4`. Resume at Stage 11. |
| **Missing speaking-rate sample** | No speaking-rate measurement in `writing/brief.md` | Ask the human to record 20 seconds of natural speech (or measure from a prior raw recording of the same speaker) before budgeting `writing/script.md`. |
| **Unsourced claim in script or speech** | Claim in `writing/script.md` or kept `asr/raw.json` has no match in `research/source_contract.md` | In Stage 3, either add a verified primary source to `research/source_contract.md` or rewrite/delete the claim. In Stage 6, cut the unsupported spoken claim in `edit/edit_plan.json` or flag it for the human if cutting breaks narrative continuity. |
| **No quiet gap on one side of a word to cut** | `vlog quiet` returns no quiet window between the target word and adjacent kept words | Expand the cut in `edit/edit_plan.json` to include the adjacent word(s) up to the nearest quiet gap that leaves a grammatical sentence. |

---

## Known Pitfalls (From Production Run)

| # | Symptom | Root Cause | Remedy |
| :--- | :--- | :--- | :--- |
| 1 | Cut defined on token timestamps leaves a filler ("呃") or the first of two repeated syllables in `audio/edited.wav` | Forced-aligner timestamps are approximate right where cuts happen (a 260 ms filler was assigned 80 ms; a repeated syllable's audio was attributed to the preceding token) | Always place cut `start` and `end` inside quiet intervals measured on the waveform with `vlog quiet`, then confirm with `vlog verify`. `vlog edit` lists edges that still sit inside speech energy under `warnings`. |
| 2 | Deleted syllable reappears at the edge of a kept island after rendering | Renderer pads island edges and extends them while energy stays high to protect consonants; unclamped extension reaches back into the cut region | Clamp edge-padding and high-energy extension in `edit.py` strictly to cut boundaries (`cuts[i].start` and `cuts[i].end`). |
| 3 | Edited audio sounds breathless and unnatural to the speaker | Compressing all breath pauses to ~0.2 s destroys natural cadence | Use the speaker-approved pacing defaults: keep natural pauses below `pacing.keep_gap_s` untouched; only shorten long stalls and refill them with measured `room_tone`, never digital silence. |
| 4 | Token-overlap heuristic flags a clean join as a residue false positive | Forced-aligner token boundaries drift near cuts, making a deleted token appear to overlap kept audio | Before moving a cut, check the 10 ms RMS energy envelope (`vlog quiet`) and the re-transcription (`asr/edited.json`). |
| 5 | Cutting a single word ("never" in "we never skip tests") clips adjacent phonemes | Continuous speech has no quiet gap on one side of the word | Delete a slightly larger phrase that has quiet gaps on both ends (for example, delete "we never") while keeping the remaining sentence grammatical. |
| 6 | Edited recording runs 17.7 minutes against a 15-minute target | Script was budgeted at a generic 240 chars/min while the speaker's conversational rate was ~310 chars/min and the speaker elaborated off-script (23 min raw) | Measure the speaker's actual speaking rate from a 20 s sample during Stage 2/3; if the edited recording still overruns, report the measured overrun to the human at Checkpoint 3 rather than cutting substantive content silently. |
| 7 | Storyboard visual cues fail to match the video timeline | Speaker departed from `writing/script.md` during recording, invalidating script anchor phrases | Key `storyboard/storyboard.md` exclusively to `asr/avatar.json` (the transcript of the final avatar video), never to `writing/script.md`. |
| 8 | Final audio contains an invented case-study mechanism, misattributed filtering behavior, overstated "never", or a relative date that goes stale | Speaker improvised off-script claims during recording that were not in `writing/script.md` | Fact-check the transcript of what was actually said (`asr/raw.json`) against `research/source_contract.md` in Stage 6 and cut or flag unsupported spoken claims. |
| 9 | Spoken instructions ("this part should be cut", "let me redo that") remain in the audio or are ignored by the editor | Speaker gives editing directions aloud in the recording | Treat spoken self-directions both as instructions to follow when designing cuts and as meta-commentary that must itself be cut and passed to `vlog verify --expect-absent`. |
| 10 | Subtitles display garbled Chinese characters in place of English technical terms ("PR", "code review", "tribal knowledge") | ASR mis-recognizes English technical terms embedded in Chinese speech even though the spoken audio is clear | Maintain `subtitles/glossary.json` and pass it to `vlog subtitles --glossary` to replace mis-recognized terms in `subtitles.srt`; leave the audio untouched. |
| 11 | Audit/status document reports projected 14.5-minute duration and obsolete pacing rules while actual output is 18 minutes | Documentation was written from pre-render projections rather than post-render artifacts | Always read and report actual measured numbers (`edited_duration_s`, `loudness.integrated_lufs`, `loudness.true_peak_dbfs`) directly from `edit/manifest.json` after every render. |
| 12 | A trailing fragment of a deleted word (half a syllable) survived at a join, and the re-transcription did not show it | The fragment was too short for ASR to emit a word, so `vlog verify` reported the join as clean | Treat a clean verify as necessary, not sufficient; when a cut edge sits close to speech energy, check the `vlog quiet` envelope at that edge, and keep the human listening checkpoint. |
