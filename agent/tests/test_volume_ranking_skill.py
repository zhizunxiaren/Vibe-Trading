"""Tests for the volume-ranking Agent skill."""

from __future__ import annotations

from pathlib import Path

from src.agent.skills import SkillsLoader


def test_volume_ranking_skill_points_to_run_analysis() -> None:
    loader = SkillsLoader(user_skills_dir=Path("agent/tests/no_user_skills"))

    content = loader.get_content("volume-ranking")

    assert '<skill name="volume-ranking">' in content
    assert "run_analysis" in content
    assert "top-volume" in content
    assert "days" in content
    assert "limit" in content
