import time
from pathlib import Path
from unittest.mock import patch

import isrc101_agent.skills as skills_module


def _write_skill(skill_dir: Path, name: str, description: str, body: str = "Use this skill"):
    target_dir = skill_dir / name
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / "SKILL.md").write_text(
        "\n".join(
            [
                "---",
                f"name: {name}",
                f"description: {description}",
                "---",
                body,
            ]
        ),
        encoding="utf-8",
    )


def test_discover_skills_uses_cache_when_unchanged(tmp_path):
    project_root = tmp_path / "project"
    skills_root = project_root / "skills"
    skills_root.mkdir(parents=True)

    _write_skill(skills_root, "python-bugfix", "Fix Python bugs")

    skills_module.clear_discovery_cache()
    original_parse = skills_module._parse_skill_file

    with patch.object(skills_module, "_parse_skill_file", side_effect=original_parse) as parse_mock:
        first = skills_module.discover_skills(project_root)
        second = skills_module.discover_skills(project_root)

    assert "python-bugfix" in first
    assert "python-bugfix" in second
    assert parse_mock.call_count == 1


def test_discover_skills_cache_invalidates_on_change(tmp_path):
    project_root = tmp_path / "project"
    skills_root = project_root / "skills"
    skills_root.mkdir(parents=True)

    _write_skill(skills_root, "python-bugfix", "Fix Python bugs", body="Version 1")

    skills_module.clear_discovery_cache()
    original_parse = skills_module._parse_skill_file

    with patch.object(skills_module, "_parse_skill_file", side_effect=original_parse) as parse_mock:
        first = skills_module.discover_skills(project_root)
        time.sleep(0.02)
        _write_skill(skills_root, "python-bugfix", "Fix Python bugs", body="Version 2 updated")
        second = skills_module.discover_skills(project_root)

    assert "Version 1" in first["python-bugfix"].instructions
    assert "Version 2 updated" in second["python-bugfix"].instructions
    assert parse_mock.call_count == 2
