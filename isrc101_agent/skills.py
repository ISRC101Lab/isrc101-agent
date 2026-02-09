"""Skill discovery and prompt assembly."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import yaml


@dataclass
class SkillSpec:
    name: str
    description: str
    path: str
    instructions: str


@dataclass
class _DiscoveryCacheEntry:
    fingerprints: tuple[tuple[str, int, int], ...]
    skills: Dict[str, SkillSpec]


_DISCOVERY_CACHE: dict[tuple[str, ...], _DiscoveryCacheEntry] = {}


def clear_discovery_cache() -> None:
    """Clear in-memory skill discovery cache."""
    _DISCOVERY_CACHE.clear()


def _parse_skill_file(skill_file: Path) -> Optional[SkillSpec]:
    try:
        raw = skill_file.read_text(encoding="utf-8")
    except OSError:
        return None

    lines = raw.splitlines()
    if not lines or lines[0].strip() != "---":
        return None

    end_index = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            end_index = index
            break
    if end_index is None:
        return None

    frontmatter_text = "\n".join(lines[1:end_index])
    instructions = "\n".join(lines[end_index + 1:]).strip()

    try:
        frontmatter = yaml.safe_load(frontmatter_text) or {}
    except yaml.YAMLError:
        return None

    if not isinstance(frontmatter, dict):
        return None

    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not name.strip():
        return None
    if not isinstance(description, str) or not description.strip():
        return None

    return SkillSpec(
        name=name.strip(),
        description=description.strip(),
        path=str(skill_file),
        instructions=instructions,
    )


def _normalize_dir(base_dir: Path, skills_dir: Optional[str]) -> Path:
    if not skills_dir:
        return base_dir / "skills"
    custom = Path(skills_dir).expanduser()
    if custom.is_absolute():
        return custom
    return base_dir / custom


def _build_search_dirs(project_root: Path, skills_dir: Optional[str]) -> List[Path]:
    primary = _normalize_dir(project_root, skills_dir)
    search_dirs: List[Path] = [primary]

    global_dir = Path.home() / ".isrc101-agent" / "skills"
    if global_dir.resolve() != primary.resolve():
        search_dirs.append(global_dir)

    return search_dirs


def _collect_skill_files(search_dirs: List[Path]) -> tuple[list[Path], tuple[tuple[str, int, int], ...]]:
    skill_files: list[Path] = []
    fingerprints: list[tuple[str, int, int]] = []

    for base_dir in search_dirs:
        if not base_dir.is_dir():
            continue

        for skill_file in sorted(base_dir.glob("*/SKILL.md")):
            skill_files.append(skill_file)
            try:
                stat = skill_file.stat()
                fingerprints.append((str(skill_file.resolve()), stat.st_mtime_ns, stat.st_size))
            except OSError:
                fingerprints.append((str(skill_file), 0, 0))

    return skill_files, tuple(fingerprints)


def discover_skills(project_root: Path, skills_dir: Optional[str] = None) -> Dict[str, SkillSpec]:
    """Discover skills from project and global directories.

    Priority:
      1) configured/project skills-dir
      2) global ~/.isrc101-agent/skills (fallback)
    """
    search_dirs = _build_search_dirs(project_root, skills_dir)
    cache_key = tuple(str(path.resolve()) for path in search_dirs)

    skill_files, fingerprints = _collect_skill_files(search_dirs)
    cached = _DISCOVERY_CACHE.get(cache_key)
    if cached and cached.fingerprints == fingerprints:
        return dict(cached.skills)

    discovered: Dict[str, SkillSpec] = {}
    for skill_file in skill_files:
        spec = _parse_skill_file(skill_file)
        if spec and spec.name not in discovered:
            discovered[spec.name] = spec

    _DISCOVERY_CACHE[cache_key] = _DiscoveryCacheEntry(
        fingerprints=fingerprints,
        skills=dict(discovered),
    )
    return dict(discovered)


def build_skill_instructions(skills: Dict[str, SkillSpec], enabled_names: List[str]) -> Tuple[str, List[str], List[str]]:
    """Build prompt text for enabled skills.

    Returns: (prompt_text, resolved_enabled_names, missing_names)
    """
    seen = set()
    resolved: List[str] = []
    missing: List[str] = []
    sections: List[str] = []

    for name in enabled_names:
        if name in seen:
            continue
        seen.add(name)

        spec = skills.get(name)
        if not spec:
            missing.append(name)
            continue

        resolved.append(name)
        body = spec.instructions.strip()
        if body:
            sections.append(f"### {spec.name}\n{body}")
        else:
            sections.append(f"### {spec.name}\n{spec.description}")

    if not sections:
        return "", resolved, missing

    prompt = (
        "## Enabled skills:\n"
        "Follow these additional instructions when they match the user request.\n\n"
        + "\n\n".join(sections)
    )
    return prompt, resolved, missing
