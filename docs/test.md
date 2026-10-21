# Testing and Acceptance Guide

## 1. Offline Automated Tests

Offline tests require Python 3.12, `numpy`, `pytest`, and `ffmpeg`/`ffprobe` on `PATH`. They require no network access, no Apple Silicon GPU, no API keys, and no real recordings. All audio and transcripts are synthesized in temporary directories during test execution.

### Running Offline Tests

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
pytest -m "not asr and not heygen_live"
```

### Offline Test Coverage Matrix

| Module / Command | What is Tested Offline | Synthetic Fixture Strategy |
| :--- | :--- | :--- |
| `edit.py` (`tests/test_edit.py`) | Cut syllables are gone and every kept syllable is present at its output time (checked by the dominant frequency of each tone burst); a 0.35 s comma pause stays exactly as recorded; a 2.2 s stall after a period is shortened to about 1 s; every island maps raw to output time with equal length; no island overlaps a cut (edge clamp); partial `pacing` overrides merge with the defaults; an inverted cut is rejected; the automatic room-tone window avoids speech. | Stereo 48 kHz recording of tone bursts (one pitch per syllable) over a -62 dBFS noise floor (`tests/synth.py`). |
| `quiet.py`, `audio.py` | Quiet runs found between bursts with `min_db` below the threshold; a trailing quiet run is closed; RMS level of a known sine. | Same synthetic recording; numpy arrays. |
| `transcribe.py`, `utterances.py` | Punctuation attached from the engine text; punctuation classes; a raw engine dump (`segments` + `chunks`) normalizes to `vlog.transcript/1`; utterances split at pauses with long gaps marked. | Small hand-written transcripts. |
| `verify.py` | A filler and a doubled syllable near a join are flagged as `review`; allow-listing and an empty filler list clear them; an expected-absent phrase anywhere in the edited text makes the report unclean. | Rendered synthetic edit plus hand-written edited transcripts. |
| `subtitles.py` | Glossary replacement, the width limit, no merge across a sentence end, trailing punctuation dropped, SRT timestamps from integer milliseconds. | Synthetic word list. |
| `heygen.py` | `create` sends the documented v3 body, `X-Api-Key` and `Idempotency-Key`; small files use multipart upload and large files the three-step direct upload; `wait` treats unknown states such as `waiting` as running; `download` writes via a `.part` file; HTTP error bodies pass through; the key is read from `.env`. | An injected opener that records requests and serves canned responses. |
| `cli.py` | Envelopes and exit codes: `init` succeeds; a missing input file exits 4; an unknown subcommand exits 2; a missing key exits 3; a failed render in `heygen wait` exits 5; an ffmpeg failure exits 5. | `cli.main([...])` with captured stdout. |

---

## 2. Tests Requiring Apple Silicon (`[asr]`)

`vlog transcribe` uses `mlx-qwen3-asr==0.4.4` (`Qwen3-ASR-1.7B` and `Qwen3-ForcedAligner-0.6B`), which requires Apple Silicon (`arm64` macOS with Metal/MLX).

### Setup and Execution

```bash
source .venv/bin/activate
uv pip install -e ".[asr,dev]"
pytest -m asr
```

### What `pytest -m asr` Verifies

1. **Audio transcription**: Synthesizes or loads a short speech fixture, runs `vlog transcribe`, and validates that the output conforms to `vlog.transcript/1` with monotonically non-decreasing word timestamps (`0 <= start <= end <= duration_s`).
2. **Video audio extraction**: Wraps the audio fixture in an `.mp4` container with a synthetic black video stream via `ffmpeg`, runs `vlog transcribe video.mp4 --out out.json`, and verifies that extraction and alignment succeed.
3. **Degraded mode on non-Apple-Silicon**: When `mlx_qwen3_asr` is not installed, `vlog transcribe` exits with code `3` and emits `{"command": "transcribe", "ok": false, "error": {"type": "MissingDependencyError", ...}}`.

---

## 3. Tests Requiring a Live HeyGen API Key (Costs Money)

The `vlog heygen` client is implemented against the HeyGen v3 API documentation (2026-10-20) and has not yet been run against a live production key. Because HeyGen API v3 bills from a separate pay-as-you-go API wallet (and video generation consumes paid credits), live tests are gated behind both a pytest marker and an explicit environment variable.

### Setup and Read-Only Smoke Test (No Render Cost)

```bash
export HEYGEN_API_KEY="your-api-key"
vlog heygen me
vlog heygen looks
```

Check that:
- `vlog heygen me` exits `0` and prints account balance/quota JSON.
- `vlog heygen looks` exits `0` and lists private digital-twin looks with `id`, `status`, and `supported_api_engines`.

### Live Upload and Short Render Test (Incurs API Charges)

Only run with a short (3–5 second) audio file after checking current v3 pricing in HeyGen's documentation:

```bash
export HEYGEN_API_KEY="your-api-key"
export HEYGEN_TEST_AVATAR_ID="your-digital-twin-look-id"
pytest -m heygen_live
```

This test:
1. Uploads a 3-second WAV file via `vlog heygen upload`.
2. Creates a 720p test video via `vlog heygen create --avatar-id "$HEYGEN_TEST_AVATAR_ID" --audio-asset-id "<asset_id>" --idempotency-key "<uuid>"`.
3. Polls via `vlog heygen wait <video_id> --timeout 1800 --interval 15`.
4. Downloads the resulting `.mp4` via `vlog heygen download <video_id> --out /tmp/heygen_smoke.mp4` and checks stream validity with `ffprobe`.

---

## 4. Manual Acceptance Checklist for a Real Production

Use this checklist when running a full episode with a human in the loop. Every item corresponds to a pipeline acceptance check or a failure mode observed in production.

### Stage 1–3: Research, Brief, and Script

- [ ] `research/source_contract.md` lists every factual claim, number, and case-study mechanism with its primary source and claim strength, separated from the author's own opinions.
- [ ] `writing/brief.md` records the human-approved thesis, target audience, and section length budget.
- [ ] Speaking rate budget in `writing/script.md` is calculated from a measured sample of the actual speaker (at least 20 seconds of conversational speech), not a generic default rate (Pitfall 6).
- [ ] Paragraphs in `writing/script.md` have stable IDs (`P01`, `P02`, ...).
- [ ] Fact-drift check and cold-read review were executed in separate contexts from script drafting, and all cold-read comprehension issues are resolved.
- [ ] Human has approved `writing/script.md`.

### Stage 4–9: Recording, Audio Editing, Verification, and Listening

- [ ] Raw recording is saved in `audio/raw/` and transcribed to `asr/raw.json` via `vlog transcribe`.
- [ ] Spoken transcript (`asr/raw.json`) has been fact-checked line by line against `research/source_contract.md` to catch off-script inventions, misattributions, overstated absolutes ("never"), or relative dates (Pitfall 8).
- [ ] Spoken self-directions ("let me redo that", "this part should be cut") are both followed as editorial instructions and cut from the audio (Pitfall 9).
- [ ] Every cut in `edit/edit_plan.json` has a `start` and `end` placed inside a quiet interval verified with `vlog quiet` on the waveform, never raw forced-aligner token boundaries alone (Pitfall 1).
- [ ] Where a single word to delete lacks a quiet gap on one side, a slightly larger surrounding phrase with clean quiet boundaries is cut so the remaining sentence stays grammatical (Pitfall 5).
- [ ] Pacing uses the speaker-approved natural pause thresholds (keeping natural breaths untouched and only shortening long stalls with room tone, never digital silence) unless the speaker requested otherwise (Pitfall 3).
- [ ] `audio/edited.wav` is re-transcribed to `asr/edited.json` and checked with `vlog verify` (including `--expect-absent` for deleted self-directions and retakes).
- [ ] Every join flagged as `"review"` by `vlog verify` has been checked against the RMS energy envelope and `asr/edited.json`, and either fixed by adjusting cut boundaries in `edit/edit_plan.json` or explained in writing (Pitfall 4).
- [ ] All reported durations and loudness (`loudness.integrated_lufs`, `loudness.true_peak_dbfs`) are read directly from the latest `edit/manifest.json`, keeping documentation in sync with the actual output (Pitfall 11).
- [ ] If the edited duration overruns the target budget, the overrun is reported to the human rather than cutting substantive content silently (Pitfall 6).
- [ ] **Human listening checkpoint**: Agent has reported `edited_duration_s`, `loudness.integrated_lufs`, `loudness.true_peak_dbfs`, and the `vlog verify` result, stated explicitly that the agent cannot hear delivery, and received human approval on `audio/edited.m4a`.

### Stage 10–15: Avatar, Subtitles, Storyboard, B-Roll, and Final QA

- [ ] Avatar video (`avatar/avatar.mp4`) is generated from the approved edited audio (via HeyGen web UI or `vlog heygen`) and verified by the human.
- [ ] `avatar/avatar.mp4` is re-transcribed to `asr/avatar.json` via `vlog transcribe` to serve as the master clock for picture and subtitles.
- [ ] `subtitles/glossary.json` includes replacements for all English technical terms and product names mis-recognized by ASR in `asr/avatar.json` (Pitfall 10).
- [ ] `subtitles/subtitles.srt` generated by `vlog subtitles` has at most ~22 CJK characters per cue and never splits a cue across a sentence boundary.
- [ ] `storyboard/storyboard.md` is keyed to exact phrases in `asr/avatar.json` (what the speaker actually said), not `writing/script.md` (Pitfall 7).
- [ ] Full-frame avatar stretches are kept short and every storyboard beat has clear visual content or typography.
- [ ] Final rendered video passes contact-sheet inspection, stream duration alignment, final audio re-transcription check, and `-16` LUFS loudness check, and is reviewed by the human before any external use.
