"""Tests for friction contract and static detector."""

import pytest
from pathlib import Path
import tempfile

from studio.friction.contract import (
    CodeQualityMetrics,
    FrictionReport,
    severity_from_score,
)
from studio.friction.detector import analyze_project


def test_severity_from_score():
    assert severity_from_score(9.0) == "critical"
    assert severity_from_score(7.0) == "high"
    assert severity_from_score(5.0) == "medium"
    assert severity_from_score(2.0) == "low"
    assert severity_from_score(0.0) == "low"


def test_friction_report_fields():
    r = FrictionReport(
        severity="high",
        category="complexity",
        description="Too complex",
        code_location="module.py:10",
        friction_score=7.5,
        suggested_design_change="Decompose",
    )
    assert r.friction_score == 7.5
    assert r.category == "complexity"


def test_analyze_project_empty_dir():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp)
        metrics, reports = analyze_project(path)
        assert isinstance(metrics, CodeQualityMetrics)
        assert isinstance(reports, list)
        # Empty project has no friction
        assert len(reports) == 0


def test_analyze_project_detects_complexity():
    """Use a non-test-named temp dir so the detector doesn't skip the files."""
    with tempfile.TemporaryDirectory(prefix="studio_src_") as tmp:
        path = Path(tmp)
        complex_code = """
def foo(x):
    if x > 0:
        for i in range(x):
            if i % 2 == 0:
                try:
                    if i > 5:
                        while i > 0:
                            i -= 1
                except Exception:
                    pass
    elif x < 0:
        if x < -10:
            for j in range(abs(x)):
                if j > 0 and j < 5:
                    pass
    return x
"""
        (path / "module.py").write_text(complex_code)
        metrics, reports = analyze_project(path)
        assert metrics.max_cyclomatic_complexity > 0


def test_analyze_project_detects_duplication():
    """Use a non-test-named temp dir so the detector doesn't skip the files."""
    with tempfile.TemporaryDirectory(prefix="studio_src_") as tmp:
        path = Path(tmp)
        # Each line >= 10 chars × 6 lines = 60+ chars (above the 50-char block threshold)
        block = "\n".join([f"value_{i:02d} = {i * 100}" for i in range(8)])
        (path / "a.py").write_text(block + "\nprint('module_a')\n")
        (path / "b.py").write_text(block + "\nprint('module_b')\n")
        metrics, reports = analyze_project(path)
        assert metrics.duplication_pct > 0
