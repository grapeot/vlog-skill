# vlog-skill

`vlog-skill` is an open-source agent skill (`skills/vlog/SKILL.md`) and Python CLI (`vlog`) for producing narrated talking-head explainer videos end to end with a human in the loop.

Given a topic or idea, the agent and human collaborate to produce a rendered video in which the speaker's own digital-twin avatar delivers the speaker's own edited voice-over, composited with B-roll (procedural animation, illustrations, screen recordings), subtitles, and a music bed.

## Who It Is For

Engineers and technical authors who use coding agents to produce narrated explainer videos using their own recorded voice and digital-twin avatar, without manual waveform cutting in a non-linear editor.

## Scope and Validation Status

`vlog-skill` was extracted from one real production: a ~17-minute Chinese technical explainer on how to do code review when AI writes code faster than people can read it. Everything not exercised in that production is marked **untested** or **planned**.

| Component | Status | Details |
| :--- | :--- | :--- |
| Research, brief, and narration script workflow | Exercised in one production | Source contract, speaking-rate budgeting, separate fact-drift and cold-read passes |
| Audio transcription (`vlog transcribe`) | Exercised in one production | Word-level timestamps via `Qwen3-ASR-1.7B` + `Qwen3-ForcedAligner-0.6B` (`mlx-qwen3-asr`, Apple Silicon) |
| Utterance splitting & quiet-gap detection (`vlog utterances`, `vlog quiet`) | Exercised in one production | Pause-split tables and 10 ms RMS envelope analysis |
| Audio editing & loudness measurement (`vlog edit`) | Exercised in one production | Raised-cosine crossfades, speaker-approved room-tone pacing, `ffmpeg ebur128` metrics, time-mapping manifest |
| Re-transcription join verification (`vlog verify`) | Exercised in one production | Compares raw vs. edited transcripts around every join and checks for absent phrases |
| Subtitle generation (`vlog subtitles`) | Implemented (v0.1) | Punctuation-chunked SRT (~22 CJK chars max per cue, never across sentence ends) with glossary replacements |
| HeyGen API v3 client (`vlog heygen`) | Implemented, untested | Built against HeyGen v3 API docs (2026-10-20); not yet exercised with a live API key (production run used the HeyGen web UI) |
| B-roll frame rendering & music generation | Delegated | Provided by sibling repository [`opus-video-audio-skill`](https://github.com/grapeot/opus-video-audio-skill) |
| Timeline compose & final ffmpeg render | Planned (v0.2) | Automated multi-mode avatar/B-roll compositing and -16 LUFS audio ducking |

### Out of Scope

- Publishing to video platforms (the agent never publishes anything)
- Text-to-video generation
- Text-to-speech (TTS) voice cloning (the voice is always the person's own recording)
- Interactive GUI non-linear editors

## Requirements and Installation

### Prerequisites

- Python 3.12
- `ffmpeg` and `ffprobe` on `PATH`
- [`uv`](https://github.com/astral-sh/uv) for virtual environment and package management
- Optional (for local `vlog transcribe`): Apple Silicon Mac for `mlx-qwen3-asr==0.4.4`

### Setup

```bash
git clone https://github.com/grapeot/vlog-skill.git
cd vlog-skill

uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'

# Optional: install ASR dependencies on Apple Silicon
uv pip install -e '.[asr]'
```

Run offline tests:

```bash
python -m pytest -q
```

## Quick Start

1. **Initialize a project directory** (outside the repository):

```bash
vlog init /path/to/project
```

2. **Research, outline, and draft script** (`research/source_contract.md`, `writing/brief.md`, `writing/script.md`), then record a continuous voice-over to `/path/to/project/audio/raw/take1.m4a`.

3. **Transcribe the raw audio**:

```bash
vlog transcribe /path/to/project/audio/raw/take1.m4a --out /path/to/project/asr/raw.json
```

4. **Inspect utterances and measure quiet gaps**:

```bash
vlog utterances /path/to/project/asr/raw.json
vlog quiet /path/to/project/audio/raw/take1.m4a --start 40.0 --end 52.0
```

5. **Write `/path/to/project/edit/edit_plan.json` and render the edit**:

```bash
vlog edit /path/to/project/edit/edit_plan.json
```

6. **Re-transcribe and verify every join** (repeat steps 4–6 until clean):

```bash
vlog transcribe /path/to/project/audio/edited.wav --out /path/to/project/asr/edited.json
vlog verify \
  --manifest /path/to/project/edit/manifest.json \
  --raw /path/to/project/asr/raw.json \
  --edited /path/to/project/asr/edited.json \
  --out /path/to/project/edit/verify_report.json \
  --markdown /path/to/project/edit/verify_report.md \
  --expect-absent "let me redo that"
```

7. **Human listening checkpoint**: Listen to `/path/to/project/audio/edited.m4a` and approve delivery and pacing.

8. **Generate the avatar video**: Upload `audio/edited.m4a` in the HeyGen web UI (or use `vlog heygen`) and save the output to `/path/to/project/avatar/avatar.mp4`.

9. **Re-transcribe avatar video and generate subtitles**:

```bash
vlog transcribe /path/to/project/avatar/avatar.mp4 --out /path/to/project/asr/avatar.json
vlog subtitles /path/to/project/asr/avatar.json \
  --glossary /path/to/project/subtitles/glossary.json \
  --out /path/to/project/subtitles/subtitles.srt
```

## CLI Summary

Every command prints a single JSON summary object to `stdout` and passes upstream errors through with raw details (HTTP status, response body, exception type).

| Command | Description | Status |
| :--- | :--- | :--- |
| `vlog init <project_dir>` | Create the standard project directory layout | Implemented, tested |
| `vlog transcribe <media> --out <json>` | Word-level ASR transcript (`mlx-qwen3-asr`); extracts audio from video via `ffmpeg` first | Implemented; the same engine and settings were used in the first production; needs Apple Silicon |
| `vlog utterances <transcript.json>` | Split transcript into utterances at pauses above threshold; print time and gap table | Implemented, tested |
| `vlog quiet <audio> --start <s0> --end <s1> [--threshold-db <db>]` | List quiet intervals (`start`, `end`, `min_db`) in a window from a 10 ms RMS envelope | Implemented, tested |
| `vlog edit <edit_plan.json>` | Render edited WAV and M4A with equal-power crossfades and room-tone pads; write manifest and `ebur128` loudness | Reproduces the first production's edit sample for sample |
| `vlog verify --manifest <m> --raw <r> --edited <e> --out <json> [--markdown <md>] [--expect-absent <str> ...]` | Compare raw vs. edited text around joins and scan for cut phrases; write JSON and Markdown reports | Run on the first production: flagged the three defects of the first edit, clean on the fixed edit |
| `vlog subtitles <transcript.json> --glossary <glossary.json> --out <srt>` | Generate SRT chunked at punctuation (max ~22 CJK chars/cue) with glossary term replacements | Implemented (v0.1) |
| `vlog heygen me` | Check `HEYGEN_API_KEY` validity and account balance (`v3` API) | Implemented, untested |
| `vlog heygen looks` | List private digital-twin looks and supported engines (`v3` API) | Implemented, untested |
| `vlog heygen upload <audio>` | Upload audio via simple (`<= 32 MB`) or 3-step direct upload (`v3` API) | Implemented, untested |
| `vlog heygen create --avatar-id <id> --audio-asset-id <id> [...]` | Create an avatar render job from uploaded audio (`v3` API) | Implemented, untested |
| `vlog heygen status <video_id>` | Poll video render status once (`v3` API) | Implemented, untested |
| `vlog heygen wait <video_id> [--timeout] [--interval]` | Poll until render reaches `completed` or `failed` (`v3` API) | Implemented, untested |
| `vlog heygen download <video_id> --out <path>` | Fetch fresh presigned URL and download rendered video (`v3` API) | Implemented, untested |

## Project Layout

### Workspace Created by `vlog init`

```text
/path/to/project/
├── research/source_contract.md
├── writing/{brief.md,script.md}
├── audio/{raw/,edited.wav,edited.m4a,music/}
├── asr/{raw.json,edited.json,avatar.json,final.json}
├── edit/{edit_plan.json,manifest.json,verify_report.json,verify_report.md}
├── avatar/avatar.mp4
├── storyboard/storyboard.md
├── subtitles/{glossary.json,subtitles.srt}
├── broll/
├── render/
└── qa/
```

### Repository Structure

```text
vlog-skill/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── skills/
│   └── vlog/
│       └── SKILL.md
├── docs/
│   ├── prd.md
│   ├── rfc.md
│   └── test.md
├── src/
│   └── vlog_skill/
│       ├── audio.py
│       ├── transcribe.py
│       ├── utterances.py
│       ├── quiet.py
│       ├── edit.py
│       ├── verify.py
│       ├── subtitles.py
│       ├── heygen.py
│       ├── project.py
│       └── cli.py
└── tests/
```

## Human-in-the-Loop Checkpoints

1. **Thesis and outline**: Human defines or approves the thesis, audience, and section budget in `writing/brief.md`.
2. **Script and voice recording**: Human approves `writing/script.md` and records the voice-over in one continuous file.
3. **Edited audio listening**: The agent cannot hear audio. It measures loudness, peak, duration, and re-transcription joins, then pauses so the human can listen to `audio/edited.m4a` and judge delivery.
4. **Avatar video generation**: Human renders the avatar video in the HeyGen web UI or approves pay-as-you-go API wallet usage via `vlog heygen`.
5. **Final QA review**: Human inspects the rendered video, contact sheets, and final transcript. The agent never publishes outputs.

## Privacy Rules

- Never commit voice recordings, transcripts, avatar videos, rendered videos, API keys, personal names, or machine-specific paths to the repository.
- All test fixtures use synthetic audio (generated sine tones and noise) and synthetic transcripts.
- `HEYGEN_API_KEY` is loaded from the environment or a gitignored `.env` file and is never printed in logs or command output.
- Project directories created by `vlog init` live outside the repository by default.

## License

MIT License. See `https://github.com/grapeot/vlog-skill` (default branch: `master`).
