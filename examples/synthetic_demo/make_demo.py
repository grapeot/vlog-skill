"""Build a tiny synthetic project (tone bursts stand in for syllables) to try `vlog edit` and `vlog verify`.

    python examples/synthetic_demo/make_demo.py /tmp/vlog_demo
    vlog edit /tmp/vlog_demo/edit/edit_plan.json
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tests"))
from synth import SR, make_recording, transcript  # noqa: E402

from vlog_skill.audio import write_wav  # noqa: E402

WORDS = [
    ("我", 1.00, 1.20, 300, ""), ("们", 1.25, 1.45, 400, "，"), ("看", 1.80, 2.00, 500, ""), ("那", 2.05, 2.25, 600, ""),
    ("错", 4.00, 4.20, 700, ""), ("要", 5.00, 5.20, 800, ""), ("要", 5.30, 5.50, 900, ""), ("好", 5.60, 5.80, 1000, "。"),
    ("完", 8.00, 8.20, 1100, "。"),
]

root = Path(sys.argv[1] if len(sys.argv) > 1 else "vlog_demo")
for d in ("audio/raw", "asr", "edit"):
    (root / d).mkdir(parents=True, exist_ok=True)
write_wav(root / "audio/raw/take1.wav", make_recording(WORDS, 10.0), SR)
(root / "asr/raw.json").write_text(json.dumps(transcript(WORDS, "audio/raw/take1.wav"), ensure_ascii=False, indent=2), encoding="utf-8")
plan = {
    "schema": "vlog.edit_plan/1",
    "source_audio": "../audio/raw/take1.wav",
    "transcript": "../asr/raw.json",
    "output_wav": "../audio/edited.wav",
    "output_m4a": "../audio/edited.m4a",
    "manifest": "manifest.json",
    "sample_rate": SR,
    "room_tone": {"start": 0.0, "end": 0.9},
    "lead_in_s": 0.40,
    "crossfade_ms": 25,
    "section_starts": [],
    "cuts": [
        {"start": 3.0, "end": 4.6, "kind": "major", "reason": "retake: speaker said 'let me redo that'"},
        {"start": 5.25, "end": 5.55, "kind": "micro", "reason": "doubled syllable"},
    ],
}
(root / "edit/edit_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
print(root / "edit/edit_plan.json")
