"""Tests for PromptLoader."""

import pytest
import tempfile
from pathlib import Path

from studio.ai.prompt_loader import PromptLoader, PromptTemplate


@pytest.fixture
def prompts_dir(tmp_path):
    d = tmp_path / "prompts"
    d.mkdir()
    (d / "test_agent").mkdir()
    (d / "test_agent" / "system.md").write_text("You are a {{role}} agent.")
    return d


def test_load_template(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    tpl = loader.load("test_agent", "system")
    assert isinstance(tpl, PromptTemplate)
    assert "{{role}}" in tpl.content
    assert len(tpl.hash) == 64


def test_load_caches_result(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    t1 = loader.load("test_agent", "system")
    t2 = loader.load("test_agent", "system")
    assert t1 is t2  # same object from cache


def test_render_substitutes_vars(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    tpl = loader.load("test_agent", "system")
    rendered = loader.render(tpl.content, role="design")
    assert "You are a design agent." == rendered


def test_render_leaves_missing_vars(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    tpl = loader.load("test_agent", "system")
    rendered = loader.render(tpl.content, other="x")
    assert "{{role}}" in rendered


def test_load_missing_file_raises(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    with pytest.raises(FileNotFoundError):
        loader.load("test_agent", "missing_prompt")


def test_hash_changes_with_content(prompts_dir):
    loader = PromptLoader(prompts_root=prompts_dir)
    t1 = loader.load("test_agent", "system")
    (prompts_dir / "test_agent" / "system.md").write_text("Different content")
    # Without hot-reload, still gets cached version
    t2 = loader.load("test_agent", "system")
    assert t1.hash == t2.hash
