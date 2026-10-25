"""本地、固定根目录的版本化技能加载器。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class LoadedSkill:
    id: str
    version: str
    content_hash: str
    instructions: str
    examples: tuple[str, ...]


_TASK_SKILLS = {
    "inventory": ("inventory-replenishment",),
    "order": ("inventory-replenishment", "supplier-comparison"),
    "supplier": ("supplier-comparison",),
    "analysis": ("procurement-report",),
    "report": ("procurement-report",),
}


def _root() -> Path:
    return Path(__file__).resolve().parents[3] / "skills"


def load_skill(skill_id: str, root: Path | None = None) -> LoadedSkill:
    base = (root or _root()).resolve()
    target = (base / skill_id / "SKILL.md").resolve()
    if target != base / skill_id / "SKILL.md" or not target.is_relative_to(base):
        raise ValueError("skill path escaped the fixed skill root")
    raw = target.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n(.*?)\n---\s*\n(.*)\Z", raw, flags=re.S)
    if not match:
        raise ValueError("skill frontmatter is missing")
    metadata, instructions = match.groups()
    declared_id = re.search(r"(?m)^id:\s*([\w-]+)\s*$", metadata)
    version = re.search(r"(?m)^version:\s*([\w.-]+)\s*$", metadata)
    if not declared_id or not version or declared_id.group(1) != skill_id:
        raise ValueError("skill id/version frontmatter is invalid")
    examples_dir = target.parent / "examples"
    examples = tuple(path.read_text(encoding="utf-8") for path in sorted(examples_dir.glob("*.md"))) if examples_dir.exists() else ()
    digest = hashlib.sha256(raw.encode("utf-8") + b"\0" + "\0".join(examples).encode("utf-8")).hexdigest()
    return LoadedSkill(skill_id, version.group(1), digest, instructions.strip(), examples)


def select_skills(task_type: str, actor: str = "main", root: Path | None = None) -> tuple[LoadedSkill, ...]:
    if actor == "analyst" and task_type in {"inventory", "supplier", "analysis", "report"}:
        selected = _TASK_SKILLS.get(task_type, ())
    elif actor == "order":
        selected = _TASK_SKILLS.get("order", ())
    else:
        selected = _TASK_SKILLS.get(task_type, ())
    return tuple(load_skill(skill_id, root) for skill_id in selected)


def render_skill_context(skills: tuple[LoadedSkill, ...]) -> str:
    """Render only selected, versioned skill content for a specialist prompt."""
    sections = []
    for skill in skills:
        examples = "\n".join(f"- {example.strip()}" for example in skill.examples)
        sections.append(
            f"## {skill.id}@{skill.version}\n{skill.instructions}"
            + (f"\n\nExamples:\n{examples}" if examples else "")
        )
    return "\n\n".join(sections)
