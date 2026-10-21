# AGENTS.md

Instructions and invariants for coding agents working in `https://github.com/grapeot/vlog-skill`.

## Exact Commands

Always check for `.venv` in the repository root first. Activate it before running any Python commands or installing dependencies with `uv pip install`.

### Environment Setup

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
```

### Optional Apple Silicon ASR Extra (`mlx-qwen3-asr==0.4.4`)

```bash
source .venv/bin/activate
uv pip install -e '.[asr]'
```

### Run Tests

Tests run offline using synthetic audio (generated tones and noise) and mocked HTTP responses:

```bash
source .venv/bin/activate
python -m pytest -q
```

## Repository Invariants

1. **Default branch is `master`**: Target `master` for all diffs, branches, and pull requests.
2. **No personal or production data**: Never commit recordings, transcripts, avatar videos, rendered outputs, API keys, personal names, or absolute paths from any developer machine. Use placeholder paths such as `/path/to/project` in documentation and synthetic fixtures in `tests/`. Project workspaces created by `vlog init` must live outside the repository by default.
3. **Secret handling**: Read `HEYGEN_API_KEY` from the environment or a gitignored `.env` file. Never echo, log, or include `HEYGEN_API_KEY` in stdout, stderr, or exception messages.
4. **One JSON summary per CLI command**: Every `vlog` subcommand must emit exactly one JSON summary object to `stdout` upon completion so calling agents can parse results deterministically.
5. **Raw error pass-through**: Do not wrap upstream failures in generic error messages. Pass through raw upstream details—including HTTP status codes, response bodies, `ffmpeg`/`ffprobe` stderr, exception types, and messages.
6. **Speaker-approved pacing defaults**: Keep the production-approved pacing defaults in `edit.py` and `edit_plan.json` (`DEFAULT_PACING` and `DEFAULT_EDGES` in `edit.py`, plus `lead_in_s: 0.40` and `crossfade_ms: 25`); `tests/test_edit.py` pins their behaviour. Keep natural pauses below the thresholds untouched; shorten only longer stalls; refill shortened pauses with measured room tone, never digital silence.
7. **Clamp edge refinement to cut boundaries**: When `edit.py` pads kept island edges or extends them while RMS energy stays high to avoid clipping consonants, clamp all extensions strictly to the neighboring cut boundaries so deleted syllables are never pulled back into the output.
8. **Honest scope labeling**: Keep `vlog heygen` documented as "implemented against the documented v3 API; not yet exercised with a real key" until a live run succeeds, and keep Stage 14 (compose and render) marked as "planned".

## Codebase Layout

```text
vlog-skill/
├── README.md
├── AGENTS.md
├── pyproject.toml
├── skills/
│   └── vlog/
│       └── SKILL.md          # Agent skill definition, stage acceptance criteria, schemas, pitfalls
├── docs/
│   ├── prd.md                # Product requirements and milestones
│   ├── rfc.md                # Architecture, schemas, algorithms, and HeyGen v3 integration design
│   └── test.md               # Offline test matrix, hardware/key-gated tests, manual QA checklist
├── src/
│   └── vlog_skill/
│       ├── __init__.py
│       ├── audio.py          # ffmpeg/ffprobe wrappers, WAV I/O, RMS envelope, ebur128 loudness
│       ├── transcribe.py     # Qwen3-ASR-1.7B + Qwen3-ForcedAligner-0.6B via mlx-qwen3-asr
│       ├── utterances.py     # Pause-threshold utterance splitter and table formatter
│       ├── quiet.py          # 10 ms RMS window scanner for finding low-energy cut boundaries
│       ├── edit.py           # Island grouping, clamped edge refinement, room-tone pacing, crossfades
│       ├── verify.py         # Join diff audit between raw and edited transcripts + absent-phrase scan
│       ├── subtitles.py      # Punctuation-aware SRT chunker (~22 CJK char limit) + glossary replacer
│       ├── heygen.py         # Standard-library HTTP client for HeyGen API v3
│       ├── project.py        # Workspace directory initializer (vlog init)
│       └── cli.py            # argparse CLI entrypoint emitting one JSON summary per command
└── tests/                    # Offline pytest suite using synthetic audio and mocked HTTP
```

### Module Responsibilities (`src/vlog_skill/`)

- `audio.py`: Low-level media utilities using `ffmpeg`, `ffprobe`, and `numpy`. Extracts mono/stereo PCM WAV, computes 10 ms RMS dB envelopes, encodes M4A, and parses `ffmpeg` `ebur128` integrated loudness and true peak.
- `transcribe.py`: Runs `Qwen3-ASR-1.7B` and `Qwen3-ForcedAligner-0.6B` through `mlx-qwen3-asr` on Apple Silicon. Extracts audio via `ffmpeg` first when given a video container (`.mp4`, `.mov`).
- `utterances.py`: Groups word tokens from `transcript.json` into utterances split at inter-word gaps above a threshold and formats a human- and agent-readable table of start/end times and pause durations.
- `quiet.py`: Scans a `[start, end]` window of an audio file using a 10 ms RMS envelope and returns contiguous quiet runs (`start`, `end`, `min_db`) below `--threshold-db`.
- `edit.py`: Converts `cuts` in `edit_plan.json` into kept audio islands, refines island edges against the waveform while clamping to cut boundaries, applies speaker-approved pause rules using sampled `room_tone` and raised-cosine crossfades, renders `edited.wav` and `edited.m4a`, and writes `manifest.json`.
- `verify.py`: Maps every cut in `edit_plan.json` through `manifest.json` to `edited.json`, compares raw vs. edited text around each join, checks for `--expect-absent` phrases and doubled characters, and writes `verify_report.json` and `verify_report.md`.
- `subtitles.py`: Applies `glossary.json` replacements to word/segment transcripts and emits `.srt` cues split at punctuation boundaries, capped at ~22 CJK characters per cue without crossing sentence ends.
- `heygen.py`: Zero-dependency (`urllib.request`) client for HeyGen API v3 (`https://api.heygen.com`, `X-Api-Key` header): `me`, `looks`, `upload` (multipart `POST /v3/assets` up to 32 MB or 3-step direct upload), `create` (`POST /v3/videos`), `status`, `wait`, and `download`.
- `project.py`: Implements `vlog init <project_dir>`, creating `research/`, `writing/`, `audio/raw/`, `audio/music/`, `asr/`, `edit/`, `avatar/`, `storyboard/`, `subtitles/`, `broll/`, `render/`, and `qa/`.
- `cli.py`: Dispatches `vlog` subcommands, enforces single-JSON-object output on `stdout`, and passes raw upstream exceptions and HTTP/subprocess error details through unmodified.
