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
| Stage 10, HeyGen (web UI or official CLI with OAuth) | Exercised in that production | Full-length render in the web UI; a 60-second test through the official CLI with OAuth (see "Avatar video with HeyGen") |
| Stage 11 (picture clock) | Exercised in the first production | `vlog offset` found 160 ms of drift in the Video Agent render; the picture is timed from its transcript |
| Stages 12–13 (storyboard, look development, B-roll) | In progress in the first production | Four look-development stills through three independent review rounds; one 33 s segment rendered both in SVG/Remotion and in Python |
| `vlog subtitles` | Implemented, tested on synthetic data | Punctuation-aware SRT with a glossary |
| Stage 14 (compose and render) | Planned | Not implemented in v0.1 |
| Stage 15 (final QA) | Designed, not yet exercised | |

### Boundaries and Responsibilities

- **Agent responsibilities**: Research and build the source contract; propose outline and draft script; run ASR transcription; analyze pauses and quiet windows; author `edit/edit_plan.json`; render and verify edited audio; generate or coordinate avatar video; re-transcribe avatar audio as the master clock; write the storyboard and subtitle glossary; generate B-roll assets; run final QA checks.
- **Human responsibilities**: Decide thesis and outline; approve script; record raw voice-over; listen to edited audio; generate or approve avatar video (and approve any credit spend); review final render.
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
4. **Checkpoint 4 — Avatar Video Generation (Stage 10)**: Human either runs the render in the HeyGen web UI, or signs in the official HeyGen CLI with OAuth and approves the credit spend before the agent starts a render.
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
- **Goal**: Generate a talking-head video of the speaker's digital twin driven by `audio/edited.wav` (see "Avatar video with HeyGen" below; vlog-skill does not wrap HeyGen).
- **Artifact**: `avatar/avatar.mp4`
- **Acceptance Criteria**:
  1. `avatar/avatar.mp4` exists and `ffprobe` confirms valid video and audio streams whose duration matches `audio/edited.wav` within 0.2 s.
  2. The offset between the avatar video's audio track and `audio/edited.wav`, measured by cross-correlation, is recorded (it was 0 ms in the one test so far).

### Stage 11: Picture Clock
- **Goal**: Establish a single timing reference that stays locked to the spoken words in `avatar/avatar.mp4` from start to end, accounting for any scene-stitching drift introduced by the avatar renderer.
- **Artifact**: Offset measurements from `vlog offset`, and the picture-clock transcript plus resolved phrase timestamps from `vlog anchors` (derived from `avatar/avatar.mp4` whenever the avatar audio drifts from `audio/edited.wav`).
- **Acceptance Criteria**:
  - Alignment between `audio/edited.wav` and `avatar/avatar.mp4` is measured at the start, middle, and end of the program with `vlog offset audio/edited.wav avatar/avatar.mp4 --at <start> <middle> <end>`.
  - If the offset is zero throughout (as observed on a 60 s direct CLI render), the edited-audio transcript can drive the picture clock.
  - If the offset is non-zero or changes over time (in the first production, a stitched Video Agent render measured 0 ms at 5 s, -92 ms at 500 s, and -160 ms at 1000 s, finishing 0.2 s shorter overall), `avatar/avatar.mp4` is transcribed directly and all visual cues (`vlog anchors`) and subtitles are timed from the avatar video's transcript rather than `audio/edited.wav`.
  - Every animation entrance and subtitle cue matches the spoken words in `avatar/avatar.mp4` across the full duration without cumulative drift.

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
| Audio offset between two files at several points | `vlog offset <reference> <other> --at <s> [<s> ...]` | Implemented (v0.1), checked on the first production's renders |
| Resolve spoken phrases to times | `vlog anchors <transcript.json> --phrase NAME=PHRASE [...] [--after <s>] [--until <s>]` | Implemented (v0.1) |
| Generate SRT with glossary | `vlog subtitles <transcript.json> --glossary <glossary.json> --out <srt>` | Implemented (v0.1) |

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

## Avatar video with HeyGen

vlog-skill does not wrap HeyGen. Render the final A-roll with Video Agent in the HeyGen web UI, and use the direct CLI render path only for short tests.

HeyGen offers two ways to bill subscription credits:

- **Web UI (default for final A-roll)**: open Video Agent, upload `audio/edited.m4a` or `audio/edited.wav`, pick the speaker's digital-twin look and engine, render, and download to `avatar/avatar.mp4`. The first production's full-length render was done this way.
- **Official HeyGen CLI with OAuth** (`heygen`, installed from HeyGen's documented installer, which verifies a checksum): sign in with `heygen auth login --oauth`. The CLI documents this path as using subscription credits, whereas `heygen auth login --api-key` bills the separate API wallet. Run `heygen auth status` to check the active credential and remaining credits, `heygen video list` to inspect jobs, and `heygen video download <id> --output-path avatar/avatar.mp4` to fetch completed renders.

Avoid an API key for long renders. HeyGen bills the API from a separate pay-as-you-go wallet at about three times the per-minute price of subscription credits (pricing pages, 2026-10-20):

| Engine (digital twin) | Subscription credits | API wallet |
| :--- | :--- | :--- |
| Avatar V | 48 credits/min | $7.20/min |
| Avatar IV (video look) | 31 credits/min | $4.83/min |
| Avatar III (video look) | 4 credits/min | $0.60/min |

Check the remaining monthly credits before a long render; one 18-minute Avatar V render uses most of a 1,000-credit month. In the first production the speaker compared engines and found Avatar III sufficient.

### Why Video Agent in the web UI is the default

- **Direct avatar renders have loop seams**: A 60-second clip rendered directly through `heygen video create` (`type: "avatar"`, Avatar III, 1080p) finished in about 100 seconds, cost 4 subscription credits, and came back as 1920x1080, 25 fps, H.264 and AAC, exactly 60.0 s long, with an audio track identical to the upload (cross-correlation offset 0 ms). However, the speaker judged its picture visibly worse than a Video Agent render with the same Avatar III engine and voice-over. Frame-difference analysis explained the difference: the direct render stayed nearly still most of the time and jumped sharply at 16.2, 22.9, 46.4, and 53.1 s (a period of about 30.2 s, consistent with seams where the training footage loops; at 16 s the head position and a hand gesture changed within one or two frames). The Video Agent render of the same audio had continuous small motion and no periodic jumps. No request field controls this for Avatar III digital twins (`motion_prompt` and `expressiveness` apply only to photo avatars or Avatar IV/V).
- **Video Agent API rejects audio input**: Video Agent (HeyGen's agent that plans and renders scenes) does not accept uploaded audio through the CLI. Calling `heygen video-agent create` with the audio passed either as an uploaded `asset_id` or as base64 MP3 fails at request time with `"Video Agent does not support asset type 'audio'"` (no credits spent). Combining the speaker's own voice with Video Agent therefore works only in the web UI.
- **Video Agent stitches scenes and drifts in time**: Because Video Agent renders the voice-over as several scenes and stitches them, its audio can drift against `audio/edited.wav`. In the first production the offset measured 0 ms at 5 s, -92 ms at 500 s, and -160 ms at 1000 s (the avatar running early, 0.2 s shorter overall). A 160 ms offset is enough to put picture and words visibly out of step. Always check alignment across the file with `vlog offset audio/edited.wav avatar/avatar.mp4 --at <start> <middle> <end>`; if the tracks are not aligned, transcribe `avatar/avatar.mp4` and time the picture from that transcript with `vlog anchors` (see Stage 11).

### Direct CLI command sequence (for short tests)

Command sequence exercised once (2026-10-20, official CLI v0.10.0, OAuth):

```bash
heygen avatar looks list --ownership private --avatar-type digital_twin   # pick the look id
heygen asset create --file clip.wav                                       # WAV or MP3, at most 32 MB
heygen video create --wait --timeout 40m --idempotency-key <key> -d '{
  "type": "avatar", "avatar_id": "<look id>", "audio_asset_id": "<asset id>",
  "engine": {"type": "avatar_iii"}, "resolution": "1080p", "aspect_ratio": "16:9", "output_format": "mp4"}'
heygen video download <video id> --output-path avatar/avatar.mp4
```

Not yet exercised: audio over 32 MB through the CLI (`heygen asset direct-uploads create` and `heygen asset complete create`, or upload an MP3 instead), a full-length render through the CLI (HeyGen's documentation gives 30 minutes per request on most pages and 10 minutes for audio input on one), and transparent `webm` output (only for a digital twin trained with matting).

## Picture: look development and rendering

### Splitting plates and code

Divide visual elements by what each element needs to do:

- **Illustration plates from an image model**: Use an image model only for figurative subjects (for example: a clerk at a desk, racehorses, a sorting machine, or a coastline). Generate all plates with one shared style paragraph (19th-century steel engraving, ink only, plain paper, no text). In the first production, the first four plates came out consistent on the first try.
- **Exact and animated elements in code**: Draw everything that must be exact or must move on a spoken word in code: labels, numbers, tables, arrows, boundaries, subtitles, and the speaker's video.
- **Constraint**: Do not generate whole frames with an image model. An image model cannot animate on a timeline, regenerating a frame alters the rest of the picture, and exact figures and Chinese text are not guaranteed.

### Printing plates onto the page

A plate whose paper background is even one or two levels off white appears as a faint rectangle when composited onto a large cream page. Before compositing:

1. Normalise the plate's paper tone to white.
2. Clamp near-white noise to exact white.
3. Feather the plate's outer edges.
4. Composite the plate onto the page with multiply blending.

### Measuring plate features in code

Do not guess plate coordinates or assume image dimensions. Read the plate's actual pixel dimensions and measure feature positions from the plate's ink in code. In the first production, captions under a sorting machine's three trays were misplaced because the code assumed a 1536x1152 plate while the file was 1280x960; locating the three trays directly from the plate's ink density fixed the caption alignment.

### Colour semantics

Assign each colour one meaning across the entire film and do not reuse it for unrelated concepts. In the first production:

- **Blue**: machine, and double check.
- **Amber**: human, cross check, and signature.
- **Grey**: system.
- **Red**: reserved for the single problem in a frame.

### Independent art-director review loop

Before showing look-development frames to the human, render stills of a few key beats and send them to an independent art-director reviewer (a separate agent scoring against a written rubric). In the first production, three rounds of review raised the rubric score for "one publication" from 5/10 to 8/10 and "the picture explains the line" from 6/10 to 8/10.

Concrete defects caught by the reviewer that the author had missed:

- **Slide-template boxes**: Bordered label boxes read as a slide deck pasted onto an engraving. Replace bordered boxes with serif captions over a coloured hand-ruled underline.
- **Geometric lines over organic drawings**: A straight boundary line drawn across an organic engraving reads as an artifact. Derive the boundary from the plate itself: for a coastline, identify land from the denser engraved texture, extract the coast position per row, and draw offset water-lines from its distance field.
- **Colour washes**: Rectangular or soft colour washes over a plate reveal the plate's bounding box. Avoid washes over plates.
- **Diagrams that state the wrong relationship**: Two ledgers meant to agree, when filled with different numbers and joined by `+` and `=`, read as addition and as disagreement everywhere. Fix the visual logic so the diagram matches the point: two identical ledgers that differ in a single cell, stacked into a third ledger that highlights only that discrepant cell in red.

### Speaker's video appearance

Do not restyle the speaker's video by default. In the first production, the reviewer suggested desaturating and warming the speaker's video to match the cream paper, but the owner preferred the original colour. Ask the human before applying colour grading to the A-roll.

### Choosing a rendering route

In the first production, the same 33-second segment was implemented twice from one shared timeline: once with SVG in a browser timeline (Remotion) and once frame by frame in Python with PIL and numpy.

| Metric / characteristic | Browser timeline (Remotion / SVG) | Python (PIL + numpy) |
| :--- | :--- | :--- |
| Picture quality | Practically identical | Practically identical |
| Render time (33 s clip) | 20 s | 25 s |
| Implementation size | 252 lines | 221 lines |
| Strengths | Live scrubbing preview; built-in stroke drawing, masks, blend modes, and web fonts | Direct per-pixel computation (ink measurement, distance fields); no second toolchain |

The owner slightly preferred the Python output, so the first production used Python. Choose the rendering route by working style and whether the scenes need per-pixel computation, not by expected picture quality.

### Acceptance Criteria

An agent can verify look development and rendering against these checks:

- **No whole-frame generation**: Every figurative asset is an isolated illustration plate without text; all text, numbers, tables, arrows, boundaries, and animations are rendered by code.
- **No visible plate bounding boxes**: Every plate's background paper is normalised and clamped to exact white, its edges are feathered, it is multiplied onto the page, and no colour wash reveals its rectangle.
- **Measured anchors**: Every caption or overlay attached to a plate feature derives its coordinates from the plate's actual pixel dimensions and measured ink features, and every timed entrance is anchored to a transcript phrase timestamp from the picture clock.
- **Publication typography and plate-derived overlays**: Captions use serif type with hand-ruled underlines rather than bordered boxes, and boundaries over organic plates are computed from the plate's pixels rather than drawn as straight lines.
- **Single colour meaning**: Every colour used in the code maps to its documented role across the film, with red appearing only on the single problem element in a frame.
- **Recorded reviewer loop**: Look-development stills of key beats have been critiqued by an independent reviewer agent with rubric scores recorded per round before human sign-off.
- **Unmodified A-roll colour by default**: The speaker's video retains its original colour unless the human explicitly requested grading.

---

## Degraded Cases

| Condition | Detection | Fallback Action |
| :--- | :--- | :--- |
| **No Apple Silicon / `mlx-qwen3-asr` unavailable** | `vlog transcribe` fails with import or platform error | Run `vlog transcribe` on an Apple Silicon machine and copy `asr/*.json` into the project, or supply an external word-level transcript formatted to the `transcript.json` schema. All other commands (`utterances`, `quiet`, `edit`, `verify`, `subtitles`, `heygen`) run on any OS with Python 3.12 and `ffmpeg`. |
| **Official HeyGen CLI not installed or not signed in** | `heygen auth status` reports no credential | Pause at Stage 10 and ask the human either to sign in with `heygen auth login --oauth` or to render in the HeyGen web UI and save the output to `avatar/avatar.mp4`. Resume at Stage 11. |
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
| 13 | Direct avatar render looks jumpy | Avatar III direct render loops the training footage; seams every ~30 s | Render the final A-roll with Video Agent; check any render with frame differences or by watching, not only its audio. |
| 14 | Picture and words drift apart over a long avatar video | Video Agent stitches scenes; audio drifted up to 160 ms over 17 minutes | `vlog offset`; if not aligned, time the picture from a transcript of the avatar video. |
| 15 | Subtitle cues ended or began with a single character ("特别便" then "宜") | Greedy packing up to a width limit splits a clause at an arbitrary character | Split clauses into the fewest near-equal pieces; never cross a sentence end (now the behaviour of `vlog subtitles`). |
| 16 | A glossary entry did not match | ASR wrote "A B赛马" with a space between Latin letters | Add the spaced form to the glossary. |
| 17 | Look-development frames read as a slide deck pasted onto an engraving | Boxes, straight geometric overlays, colour washes, guessed positions | Independent reviewer every round; captions not boxes; derive overlays from the plate; measure positions from the plate. |
