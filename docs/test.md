# Testing and Acceptance Guide

## 1. Offline Automated Tests

Offline tests require Python 3.12, `numpy`, `pytest`, and `ffmpeg`/`ffprobe` on `PATH`. They require no network access, no Apple Silicon GPU, no API keys, and no real recordings. All audio and transcripts are synthesized in temporary directories during test execution.

### Running Offline Tests

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
python -m pytest -q
```

### Offline Test Coverage Matrix

| Module / Command | What is Tested Offline | Synthetic Fixture Strategy |
| :--- | :--- | :--- |
| `edit.py` (`tests/test_edit.py`) | Cut syllables are gone and every kept syllable is present at its output time (checked by the dominant frequency of each tone burst); a 0.35 s comma pause stays exactly as recorded; a 2.2 s stall after a period is shortened to about 1 s; every island maps raw to output time with equal length; no island overlaps a cut (edge clamp); partial `pacing` overrides merge with the defaults; an inverted cut is rejected; the automatic room-tone window avoids speech. | Stereo 48 kHz recording of tone bursts (one pitch per syllable) over a -62 dBFS noise floor (`tests/synth.py`). |
| `quiet.py`, `audio.py` | Quiet runs found between bursts with `min_db` below the threshold; a trailing quiet run is closed; RMS level of a known sine. | Same synthetic recording; numpy arrays. |
| `transcribe.py`, `utterances.py` | Punctuation attached from the engine text; punctuation classes; a raw engine dump (`segments` + `chunks`) normalizes to `vlog.transcript/1`; utterances split at pauses with long gaps marked. | Small hand-written transcripts. |
| `verify.py` | A filler and a doubled syllable near a join are flagged as `review`; allow-listing and an empty filler list clear them; an expected-absent phrase anywhere in the edited text makes the report unclean. | Rendered synthetic edit plus hand-written edited transcripts. |
| `subtitles.py` | Glossary replacement, the width limit, no merge across a sentence end, trailing punctuation dropped, SRT timestamps from integer milliseconds. | Synthetic word list. |
| `align.py`, `subtitles.py` (`tests/test_align_subtitles.py`) | A 120 ms shift between two synthetic recordings is measured to within 2 ms and an identical pair reads as aligned; phrases resolve to the first match after `--after`, spaced and unspaced Latin match, a missing phrase raises; a long clause splits into near-equal cues with no orphan; sentence ends are respected. | Synthetic tone-burst recordings and word lists. |
| `clip.py` (`tests/test_clip.py`) | Segment parsing; SRT parsing and edge-in-cue / cue-gap classification; crossfade and hold arithmetic; top-level MP4 box order (faststart); end to end on a synthetic film: two segments joined, held, encoded as H.264 High / yuv420p / AAC with faststart, length within 0.15 s of the expected value, loudness within 1.5 LU of -16, stills written, no warnings; an edge inside a cue and inside speech plus an over-length clip all produce warnings; a segment past the end exits 4; with `--hold-end`, the last 100 ms before the hold are at least 12 dB below the steady bed and the hold is silent; a source title tag and chapters do not reach the clip, which has exactly one video and one audio stream; a tone bed with no speech yields `edge_check_skipped`; target LRA and the true-peak / LRA conditions for linear `loudnorm`; `loudness_off_target` for a peak-bound source pushed to -10 LUFS and `true_peak_over` (measured value patched); an end card from a source frame becomes the last frame (pixel comparison with that frame), is silent, and adds hold + card to the length; an image card is letterboxed in; a card time inside a cue warns and a time past the end exits 4. | `ffmpeg` `testsrc2` picture muxed with the tone-burst recording (0.1 s bursts every 0.25 s, so the envelope has speech-like gaps) and a hand-written SRT; a second film with a continuous 220 Hz bed, an `ffmetadata` title and two chapters. |
| `cli.py` | Envelopes and exit codes: `init` succeeds; a missing input file exits 4; an unknown subcommand (including the removed `heygen`) exits 2 with a JSON usage error; an ffmpeg failure exits 5. | `cli.main([...])` with captured stdout. |

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

## 3. HeyGen (manual, spends subscription credits)

vlog-skill does not call HeyGen. To check the avatar step, sign in the official CLI with `heygen auth login --oauth`, render a short clip (a 60 s Avatar III render cost 4 subscription credits in the first test), download it, and compare its audio track with the uploaded audio by cross-correlation (the first test measured 0 ms). Judge image quality by eye against a render from the web UI or Video Agent.

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

- [ ] Avatar video (`avatar/avatar.mp4`) is generated from the approved edited audio (via the HeyGen web UI or the official HeyGen CLI) and verified by the human.
- [ ] `avatar/avatar.mp4` is re-transcribed to `asr/avatar.json` via `vlog transcribe` to serve as the master clock for picture and subtitles.
- [ ] `subtitles/glossary.json` includes replacements for all English technical terms and product names mis-recognized by ASR in `asr/avatar.json` (Pitfall 10).
- [ ] `subtitles/subtitles.srt` generated by `vlog subtitles` has at most ~22 CJK characters per cue and never splits a cue across a sentence boundary.
- [ ] `storyboard/storyboard.md` is keyed to exact phrases in `asr/avatar.json` (what the speaker actually said), not `writing/script.md` (Pitfall 7).
- [ ] Full-frame avatar stretches are kept short and every storyboard beat has clear visual content or typography.
- [ ] Final rendered video passes contact-sheet inspection, stream duration alignment, final audio re-transcription check, and `-16` LUFS loudness check, and is reviewed by the human before any external use.

### Stage 16: Distribution Clips (optional)

- [ ] `vlog clip` ran against the subtitles burned into the finished film (its own clock), and `warnings` is empty or every item is explained (`edge_check_skipped` is expected only for music-only segments such as a title card).
- [ ] The first frame is fully drawn and works as a thumbnail; the body ends on a finished picture with no half-displayed subtitle (Pitfall 31).
- [ ] The last frame is the branded end card: fully faded in, readable, no subtitle, visible for about 2–3 s; the clip including the card is still within the platform limit.
- [ ] The clip, re-transcribed with `vlog transcribe`, starts and ends on the intended words with no clipped syllable.
- [ ] `normalization_type` is `linear`, integrated loudness is -16 +/- 0.5 LUFS (or the requested `--lufs` +/- 0.5), true peak at or below -1 dBTP (Pitfall 33).
- [ ] With the default 0.5 s fade, RMS before the end hold reads full level at -0.6 s, fading from -0.5 s, and at least 12 dB down in the last 100 ms of the body; the hold is silent (Pitfall 34).
- [ ] The human has played the clip through and approved the joins, fades and final hold.
- [ ] Duration is within the target platform's limit (140 s for X without Premium).
- [ ] Nothing was uploaded or posted by the agent.
