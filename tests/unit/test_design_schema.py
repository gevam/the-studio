"""Tests for LivingDesign schema."""

import json
import pytest
from studio.design.schema import LivingDesign, ModuleBoundary, DesignSection


def test_living_design_defaults():
    d = LivingDesign()
    assert d.version == 1
    assert d.modules == []
    assert d.open_questions == []


def test_compute_and_set_hash():
    d = LivingDesign(version=1, open_questions=["Why?"])
    d2 = d.compute_and_set_hash()
    assert d2.content_hash != ""
    assert len(d2.content_hash) == 64  # SHA-256 hex


def test_hash_changes_with_content():
    d1 = LivingDesign(version=1, open_questions=["A"])
    d2 = LivingDesign(version=1, open_questions=["B"])
    assert d1.compute_and_set_hash().content_hash != d2.compute_and_set_hash().content_hash


def test_hash_changes_with_version():
    """Version bump changes the content hash (version is part of the hashed content)."""
    d1 = LivingDesign(version=1, open_questions=["same"])
    d2 = LivingDesign(version=2, open_questions=["same"])
    h1 = d1.compute_and_set_hash().content_hash
    h2 = d2.compute_and_set_hash().content_hash
    assert h1 != h2  # version is included in the hash


def test_model_dump_roundtrip():
    d = LivingDesign(
        version=2,
        open_questions=["Q1"],
        modules=[
            ModuleBoundary(
                name="cli",
                responsibility="Entry point",
                interfaces=["CLIProtocol"],
                dependencies=[],
                injection_points=["storage"],
            )
        ],
    )
    json_str = d.model_dump_json()
    d2 = LivingDesign(**json.loads(json_str))
    assert d2.version == 2
    assert d2.modules[0].name == "cli"
