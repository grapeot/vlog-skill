"""`vlog` command line. Every command prints one JSON envelope to stdout.

Success: {"command": ..., "ok": true, "data": {...}}
Failure: {"command": ..., "ok": false, "error": {"type", "message", "details"}}
Exit codes: 0 ok, 2 usage, 3 missing dependency, 4 bad input, 5 external tool failure (ffmpeg).
"""

from __future__ import annotations

import argparse
import json
import sys
import traceback
from pathlib import Path

from . import __version__
from .audio import DependencyError, ToolError

EXIT_OK, EXIT_USAGE, EXIT_DEPENDENCY, EXIT_INPUT, EXIT_TOOL = 0, 2, 3, 4, 5


class UsageError(Exception):
    pass


class JsonArgumentParser(argparse.ArgumentParser):
    """Report usage errors through the JSON envelope instead of argparse's stderr text."""

    def error(self, message):
        raise UsageError(f"{self.prog}: {message}")


def _emit(command: str, data: dict | None = None, error: dict | None = None) -> None:
    env = {"command": command, "ok": error is None}
    env["data" if error is None else "error"] = data if error is None else error
    sys.stdout.write(json.dumps(env, ensure_ascii=False, indent=2) + "\n")


def _write_json(path: str | Path, doc: dict) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(doc, ensure_ascii=False, indent=2), encoding="utf-8")


def cmd_init(a) -> dict:
    from .project import init_project

    return init_project(a.project_dir, a.topic or "", a.allow_inside_repo)


def cmd_transcribe(a) -> dict:
    from .transcribe import transcribe

    doc = transcribe(a.media, model=a.model, aligner=a.aligner, language=a.language, context=a.context or "")
    _write_json(a.out, doc)
    return {"out": a.out, "words": len(doc["words"]), "duration_s": doc["duration_s"], "truncated": doc.get("truncated", False)}


def cmd_utterances(a) -> dict:
    from .transcribe import load_transcript
    from .utterances import format_table, split_utterances

    utts = split_utterances(load_transcript(a.transcript)["words"], a.min_gap)
    table = format_table(utts, a.long_gap)
    if a.out:
        Path(a.out).write_text(table, encoding="utf-8")
    long_gaps = [u for u in utts if u["gap_after"] is not None and u["gap_after"] >= a.long_gap]
    return {"out": a.out, "utterances": len(utts), "long_gaps": len(long_gaps),
            "long_gap_total_s": round(sum(u["gap_after"] for u in long_gaps), 2),
            "table": None if a.out else table}


def cmd_quiet(a) -> dict:
    from .quiet import find_quiet_runs

    res = find_quiet_runs(a.audio, a.start, a.end, a.threshold_db, a.min_duration)
    if not a.envelope:
        res.pop("envelope_db")
    return res


def cmd_edit(a) -> dict:
    from .edit import load_plan, render

    plan = load_plan(a.plan)
    m = render(plan)
    keys = ("output_wav", "output_m4a", "raw_duration_s", "edited_duration_s", "peak_linear", "loudness")
    return {k: m[k] for k in keys} | {"manifest": plan["manifest"], "cuts": len(m["cuts"]), "islands": len(m["islands"]),
                                      "dropped_islands": m["dropped_islands"], "warnings": m["warnings"]}


def cmd_verify(a) -> dict:
    from .transcribe import load_transcript
    from .verify import to_markdown, verify

    manifest = json.loads(Path(a.manifest).read_text(encoding="utf-8"))
    report = verify(manifest, load_transcript(a.raw)["words"], load_transcript(a.edited),
                    expect_absent=a.expect_absent, fillers=a.filler or None, allow_doubles=a.allow_double)
    _write_json(a.out, report)
    if a.markdown:
        Path(a.markdown).write_text(to_markdown(report), encoding="utf-8")
    flagged = [{"out_time": j["out_time"], "issues": j["issues"], "edited": j["edited"]} for j in report["joins"] if j["status"] != "ok"]
    return {"out": a.out, "markdown": a.markdown, "clean": report["clean"], "joins_checked": report["joins_checked"],
            "joins_flagged": report["joins_flagged"], "flagged": flagged, "expect_absent_hits": report["expect_absent_hits"]}


def cmd_subtitles(a) -> dict:
    from .subtitles import build_cues, to_srt
    from .transcribe import load_transcript

    glossary = json.loads(Path(a.glossary).read_text(encoding="utf-8")) if a.glossary else {}
    cues = build_cues(load_transcript(a.transcript)["words"], a.max_width, glossary=glossary)
    Path(a.out).write_text(to_srt(cues), encoding="utf-8")
    short = [c for c in cues if c["end"] - c["start"] < 1.3]
    return {"out": a.out, "cues": len(cues), "short_cues": [{"start": round(c["start"], 2), "text": c["text"]} for c in short]}


def build_parser() -> argparse.ArgumentParser:
    p = JsonArgumentParser(prog="vlog", description=__doc__.splitlines()[0])
    p.add_argument("--version", action="version", version=__version__)
    sub = p.add_subparsers(dest="command", required=True)

    s = sub.add_parser("init", help="create a project directory layout")
    s.add_argument("project_dir")
    s.add_argument("--topic")
    s.add_argument("--allow-inside-repo", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("transcribe", help="word-level transcript (Apple Silicon, extra [asr])")
    s.add_argument("media")
    s.add_argument("--out", required=True)
    s.add_argument("--model", default="Qwen/Qwen3-ASR-1.7B")
    s.add_argument("--aligner", default="Qwen/Qwen3-ForcedAligner-0.6B")
    s.add_argument("--language", help="for example Chinese or English")
    s.add_argument("--context", help="terms to bias recognition, such as product names")
    s.set_defaults(func=cmd_transcribe)

    s = sub.add_parser("utterances", help="pause-split table of a transcript")
    s.add_argument("transcript")
    s.add_argument("--out")
    s.add_argument("--min-gap", type=float, default=0.35)
    s.add_argument("--long-gap", type=float, default=0.8)
    s.set_defaults(func=cmd_utterances)

    s = sub.add_parser("quiet", help="quiet runs in a window, for placing cut edges")
    s.add_argument("audio")
    s.add_argument("--start", type=float, required=True)
    s.add_argument("--end", type=float, required=True)
    s.add_argument("--threshold-db", type=float, default=-40.0)
    s.add_argument("--min-duration", type=float, default=0.03)
    s.add_argument("--envelope", action="store_true", help="also print the 10 ms dB envelope")
    s.set_defaults(func=cmd_quiet)

    s = sub.add_parser("edit", help="render an edit plan to audio plus manifest")
    s.add_argument("plan")
    s.set_defaults(func=cmd_edit)

    s = sub.add_parser("verify", help="check every join against a fresh transcript of the edit")
    s.add_argument("--manifest", required=True)
    s.add_argument("--raw", required=True, help="transcript of the raw recording")
    s.add_argument("--edited", required=True, help="transcript of the edited audio")
    s.add_argument("--out", required=True)
    s.add_argument("--markdown")
    s.add_argument("--expect-absent", action="append", default=[], help="phrase that must not survive (repeatable)")
    s.add_argument("--filler", action="append", default=[], help="override the filler list (repeatable)")
    s.add_argument("--allow-double", action="append", default=[], help="legitimate doubled characters, e.g. 看看")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("subtitles", help="SRT from a transcript with a glossary")
    s.add_argument("transcript")
    s.add_argument("--out", required=True)
    s.add_argument("--glossary", help="JSON object mapping mis-recognized text to the correct text")
    s.add_argument("--max-width", type=float, default=22.0)
    s.set_defaults(func=cmd_subtitles)

    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        args = parser.parse_args(argv)
    except UsageError as exc:
        _emit("vlog", error={"type": "UsageError", "message": str(exc), "details": None})
        return EXIT_USAGE
    except SystemExit as exc:  # --help and --version print text for humans
        return EXIT_USAGE if exc.code not in (0, None) else EXIT_OK
    command = args.command
    try:
        _emit(command, args.func(args))
        return EXIT_OK
    except DependencyError as exc:
        _emit(command, error={"type": "DependencyError", "message": str(exc), "details": None})
        return EXIT_DEPENDENCY
    except Exception as exc:  # noqa: BLE001 - pass every detail through
        if isinstance(exc, ToolError):
            _emit(command, error={"type": "ToolError", "message": str(exc), "details": None})
            return EXIT_TOOL
        _emit(command, error={"type": type(exc).__name__, "message": str(exc), "details": traceback.format_exc(limit=3)})
        return EXIT_INPUT


if __name__ == "__main__":
    raise SystemExit(main())
