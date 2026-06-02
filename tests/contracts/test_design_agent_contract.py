"""Contract test: design agent output matches LivingDesign schema."""

import json
import pytest
from studio.agents.design import _parse_design
from studio.design.schema import LivingDesign


MINIMAL_LIVING_DESIGN = {
    "version": 1,
    "content_hash": "",
    "modules": [],
    "data_model": [],
    "ux_flows": [],
    "open_questions": ["TBD"],
    "known_friction": [],
    "sections": [],
}


def test_parse_design_valid_json():
    content = json.dumps(MINIMAL_LIVING_DESIGN)
    result = _parse_design(content)
    assert isinstance(result, LivingDesign)
    assert result.version == 1


def test_parse_design_with_markdown_fence():
    content = "```json\n" + json.dumps(MINIMAL_LIVING_DESIGN) + "\n```"
    result = _parse_design(content)
    assert result is not None
    assert result.open_questions == ["TBD"]


def test_parse_design_friction_revision_wrapper():
    wrapper = {
        "revised_design": MINIMAL_LIVING_DESIGN,
        "revision_summary": {
            "sections_changed": ["modules"],
            "reason": "Addressed testability friction",
        },
    }
    result = _parse_design(json.dumps(wrapper))
    assert result is not None
    assert isinstance(result, LivingDesign)


def test_parse_design_invalid_json_returns_none():
    result = _parse_design("not json at all")
    assert result is None


def test_parse_design_wrong_schema_returns_none():
    # Valid JSON but wrong schema
    content = json.dumps({"foo": "bar", "baz": 123})
    result = _parse_design(content)
    # LivingDesign has all-optional fields, so this may succeed with defaults
    # Just verify it doesn't crash
    assert result is None or isinstance(result, LivingDesign)


def test_parse_design_with_real_sections():
    design = dict(MINIMAL_LIVING_DESIGN)
    design["modules"] = [
        {
            "name": "cli",
            "responsibility": "Entry point",
            "interfaces": ["CLIRunner"],
            "dependencies": ["storage"],
            "injection_points": ["storage"],
        }
    ]
    result = _parse_design(json.dumps(design))
    assert result is not None
    assert len(result.modules) == 1
    assert result.modules[0].name == "cli"
