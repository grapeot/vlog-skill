"""Project directory layout for one video."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

LAYOUT = ["research", "writing", "audio/raw", "audio/music", "asr", "edit", "avatar", "storyboard", "subtitles", "broll", "render", "qa"]


def _inside_skill_repo(path: Path) -> Path | None:
    for parent in [path, *path.parents]:
        if (parent / "skills" / "vlog" / "SKILL.md").is_file() and (parent / "src" / "vlog_skill").is_dir():
            return parent
    return None


def init_project(root: str | Path, topic: str = "", allow_inside_repo: bool = False) -> dict:
    root = Path(root).resolve()
    repo = _inside_skill_repo(root)
    if repo and not allow_inside_repo:
        # recordings and transcripts must never end up in the public repository
        raise ValueError(f"{root} is inside the vlog-skill repository ({repo}); create projects elsewhere")
    created = []
    for sub in LAYOUT:
        d = root / sub
        if not d.exists():
            d.mkdir(parents=True)
            created.append(sub)
    meta = root / "project.json"
    if not meta.exists():
        meta.write_text(json.dumps({"topic": topic, "created": date.today().isoformat()}, ensure_ascii=False, indent=2) + "\n",
                        encoding="utf-8")
        created.append("project.json")
    return {"root": str(root), "created": created, "layout": LAYOUT}
