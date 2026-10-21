# Product Requirements Document: `vlog-skill`

## 1. Problem

Producing a narrated talking-head explainer video from a rough idea requires research, script writing, voice recording, waveform-accurate audio editing, avatar video generation, storyboarding, B-roll creation, and final compositing.

In practice, automating this workflow with an AI agent fails at four points without specialized tooling and explicit human checkpoints:

1. **Inaccurate word timestamps around disfluencies**: Forced aligners assign approximate boundaries to fillers, stutters, and repeated syllables. Cutting directly on token timestamps leaves audible artifacts or clips adjacent consonants.
2. **Unnatural pause compression**: Uniformly tightening pauses strips natural breathing cadences and replaces room tone with digital silence.
3. **Off-script drift during recording**: Human speakers improvise, utter self-directions ("let me redo that"), change phrasing, and introduce unverified claims not present in the written script. Storyboards keyed to the written script go out of sync, and fact-checks performed only on the written script miss spoken inaccuracies.
4. **Blind spots in agent perception**: An agent cannot hear audio delivery or judge visual pacing directly; it must rely on waveform measurements, re-transcription verification, and explicit handoffs to the human.

## 2. Users

Engineers and technical creators who:

- Record their own voice-over rather than using text-to-speech (TTS) voice cloning.
- Use their own digital-twin avatar (via HeyGen) combined with diagrams, animations, and screen recordings.
- Work with an AI coding agent on macOS or Linux and want deterministic CLI tools, inspectable JSON artifacts, and auditable verification at each stage.

## 3. Scope and Validation Status

Repository: `https://github.com/grapeot/vlog-skill` (MIT license, default branch `master`).

| Capability | Status | Notes |
| :--- | :--- | :--- |
| Project layout initialization (`vlog init`) | Implemented (v0.1) | Validated workflow structure |
| Word-level ASR + alignment (`vlog transcribe`) | Implemented (v0.1) | Exercised in production via `mlx-qwen3-asr` on Apple Silicon |
| Pause-split utterance inspection (`vlog utterances`) | Implemented (v0.1) | Exercised in production |
| RMS quiet-gap detection (`vlog quiet`) | Implemented (v0.1) | Exercised in production |
| Waveform-clamped audio editing (`vlog edit`) | Implemented (v0.1) | Exercised in production; speaker-approved pacing defaults |
| Closed-loop join verification (`vlog verify`) | Implemented (v0.1) | Exercised in production; caught 3 join defects in first pass |
| Subtitle generation with glossary (`vlog subtitles`) | Implemented (v0.1) | Punctuation-chunked SRT with term replacement |
| HeyGen, used directly (web UI or official CLI with OAuth) | Exercised in the first production | Full-length render in the web UI; a 60 s test through the official CLI with OAuth; subscription credits |
| B-roll rendering & music generation | External sibling project | Provided by `https://github.com/grapeot/opus-video-audio-skill` |
| Timeline composition & render (`vlog compose`) | Planned (v0.2) | `ffmpeg` layout modes, subtitle burn-in/mux, ducked music mix |

The pipeline was built and validated on one production: an approximately 17.7-minute Chinese technical explainer on code review when AI writes code faster than humans can read it (edited down from a 23-minute raw recording against a 15-minute target).

## 4. Human-in-the-Loop Responsibilities

| Stage | Agent Responsibility | Human Responsibility |
| :--- | :--- | :--- |
| 1. Research | Compile verified facts, sources, and claim strength in `research/source_contract.md`. | Supply domain judgment and review separate author opinions. |
| 2. Thesis & Outline | Draft `writing/brief.md` with section length budgets. | Decide the core thesis, target audience, and outline structure. |
| 3. Script | Draft `writing/script.md` (paragraphs `P01`...), run fact-drift and cold-read checks in separate contexts. | Approve the script before recording; provide a 20-second speech sample for rate calibration if needed. |
| 4. Recording | None. | Record continuous raw voice audio (`audio/raw/`), speaking retakes or self-directions aloud as needed. |
| 5–8. Audio Edit & Verify | Transcribe raw audio, fact-check spoken transcript against source contract, snap cuts to quiet gaps, render edit, re-transcribe, and iterate `vlog verify` until clean. | None during iteration. |
| 9. Listening Checkpoint | Report duration, LUFS loudness, true peak, and verification summary; state plainly that the agent cannot hear delivery. | Listen to `audio/edited.m4a` and approve pacing and cuts, or request adjustments. |
| 10–11. Avatar Video | With the human's approval, render through the official HeyGen CLI (OAuth), or ask the human to use the web UI; check the audio offset and establish the picture clock. | Sign in or render, and approve the credit spend. |
| 12–13. Storyboard & B-Roll | Key `storyboard/storyboard.md` to the avatar transcript phrases; generate B-roll assets. | Review visual style and B-roll beats. |
| 14–15. Render & QA | Assemble timeline, verify stream durations, generate contact sheets, and re-transcribe final audio. | Watch the final render and publish manually outside the tool. |

## 5. Goals

1. **Source traceability**: Every number and attributed claim in both the script and the final kept speech must trace to `research/source_contract.md`.
2. **Artifact-free audio cuts**: Every cut boundary is placed inside a measured quiet interval on the waveform, refined without crossing adjacent cut boundaries, and joined with 25 ms equal-power crossfades and room-tone fills.
3. **Closed-loop verification**: Edited audio is always re-transcribed and checked with `vlog verify` to detect residual fillers, doubled syllables, or uncut phrases before human review.
4. **Deterministic CLI contract**: Every `vlog` command outputs a single JSON result envelope to stdout and passes error details (`ffmpeg` stderr, exception type) through without wrapping.
5. **Graceful degradation**: The toolset operates when optional pieces are absent (e.g., running editing and verification when `mlx-qwen3-asr` is unavailable by accepting pre-computed transcripts).

## 6. Non-Goals

- **Publishing**: The agent and CLI never upload or publish videos to YouTube, Bilibili, X, or any other platform.
- **Text-to-speech (TTS) or voice cloning**: The narration track is always an edit of the human speaker's real recording.
- **Generative text-to-video**: Visuals consist of a lip-synced digital-twin avatar plus structured B-roll (procedural animations, consistent illustrations, screen captures).
- **Interactive GUI editors**: `vlog` is a file-based CLI driven by JSON plans and inspected via transcripts and manifests, not a non-linear editor (NLE).
- **Duplicating B-roll/music synthesis**: Procedural frame rendering and music generation remain in `https://github.com/grapeot/opus-video-audio-skill`.

## 7. Success Criteria

Each criterion is verifiable by an agent inspecting the project directory and command outputs with no external context:

1. **Fact traceability**: Every numeric value and attributed statement in `writing/script.md` and in the kept words of `edit/manifest.json` corresponds to a cited entry in `research/source_contract.md`.
2. **Waveform-quiet cut boundaries**: For every `{start, end}` cut in `edit/edit_plan.json`, both `start` and `end` lie inside quiet intervals reported by `vlog quiet` on `source_audio`.
3. **Clean verification pass**: Running `vlog verify` on the re-transcribed edited audio returns `"clean": true` (no flagged joins and no `expect_absent_hits`), or every flagged join has a documented explanation in the edit report.
4. **Manifest accuracy**: `edit/manifest.json` exists, `edited_duration_s` matches the `ffprobe` duration of `audio/edited.wav` within 10 ms, and `loudness` (`integrated_lufs`, `true_peak_dbfs`) is recorded.
5. **Transcript-locked storyboard**: Every segment anchor phrase in `storyboard/storyboard.md` appears verbatim in the transcript of `avatar/avatar.mp4`.
6. **Repository hygiene**: `git status` and staged diffs contain no `.wav`, `.m4a`, `.mp4`, real transcripts, personal names, machine-specific absolute paths, or API keys.

## 8. Milestones

### v0.1: Audio Pipeline, Verification, and Subtitles (Current)

- `vlog init`: Create project directory tree outside the repo.
- `vlog transcribe`: Word-level ASR and forced alignment via `mlx-qwen3-asr` (`Qwen3-ASR-1.7B` + `Qwen3-ForcedAligner-0.6B`) on Apple Silicon, with automatic `ffmpeg` audio extraction for video inputs.
- `vlog utterances`: Pause-segmented utterance table for reading transcripts and planning cuts.
- `vlog quiet`: 10 ms RMS envelope scanner to locate quiet intervals for cut edges.
- `vlog edit`: Waveform editor implementing word midpoint filtering, island grouping, cut-clamped edge refinement, speaker-approved room-tone pause pacing, 25 ms equal-power crossfades, WAV/M4A export, `ebur128` loudness measurement, and manifest generation.
- `vlog verify`: Join comparator and `expect-absent` scanner generating JSON and Markdown reports.
- `vlog subtitles`: Punctuation-chunked SRT generator (~22 CJK characters max per cue, never crossing sentence ends) with glossary replacement for ASR mis-recognitions.
- HeyGen guidance in the skill: use the web UI or the official HeyGen CLI with OAuth (subscription credits); a `vlog heygen` API-key client was written and then removed because the API wallet costs about three times as much per minute.
- Agent skill specification (`skills/vlog/SKILL.md`) and offline test suite.

### v0.2: Timeline Composition and Rendering (Planned)

- Define `vlog.timeline/1` JSON schema binding `avatar/avatar.mp4`, B-roll clips/frame sequences, sound effects, music bed, and SRT subtitles.
- Implement `vlog compose <timeline.json>` driving `ffmpeg` filtergraphs for the four composition modes:
  1. Avatar full frame
  2. Avatar in a side panel with B-roll
  3. Avatar in a corner over full-frame B-roll
  4. B-roll only
- Automatic audio ducking of the music bed under narration and final master normalization to `-16.0` LUFS integrated.
- Simultaneous subtitle burn-in and soft-subtitle stream muxing.

### Later

- If HeyGen rejects long audio through the CLI, split the edited audio at long pauses and join the renders locally, sample-accurately.
- `vlog qa` subcommand to generate frame contact sheets and verify stream durations and sync automatically.
