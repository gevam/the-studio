"""Unit tests for the static friction detector.

Regression: analyze_project used to rglob every *.py under the project, including
a project-local .venv, and measured complexity across whole files. A single
vendored file (e.g. mypy/checker.py) yielded cyclomatic_complexity ~3437, which
overflowed slices.cyclomatic_complexity NUMERIC(5,2) and crashed skeleton_build.
"""

from __future__ import annotations

from pathlib import Path

from studio.friction.detector import (
    _cyclomatic_complexity,
    _is_vendored,
    analyze_project,
)


def test_complexity_is_per_function_not_whole_file():
    # Two simple functions in one file: max should reflect ONE function, not the sum.
    source = (
        "def a(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    return 0\n"
        "\n"
        "def b(x):\n"
        "    if x:\n"
        "        return 1\n"
        "    return 0\n"
    )
    # Each function: 1 + one `if` = 2. Whole-file keyword counting would give 3.
    assert _cyclomatic_complexity(source) == 2


def test_complexity_counts_boolean_operators():
    source = "def f(x, y, z):\n    if x and y or z:\n        return 1\n    return 0\n"
    # base 1 + if 1 + (3 boolop values - 1) = 4
    assert _cyclomatic_complexity(source) == 4


def test_complexity_falls_back_on_syntax_error():
    assert _cyclomatic_complexity("def broken(:\n  ???") >= 1


def test_is_vendored_detects_common_dirs():
    assert _is_vendored(Path("proj/.venv/lib/python3.12/site-packages/x.py"))
    assert _is_vendored(Path("proj/node_modules/y.py"))
    assert _is_vendored(Path("proj/src/pkg.egg-info/foo.py"))
    assert not _is_vendored(Path("proj/src/todo_cli/cli.py"))


def test_analyze_project_excludes_vendored_dirs(tmp_path):
    # Real project source: one small function.
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def main():\n    if True:\n        return 1\n    return 0\n")

    # A vendored file with absurd complexity that must NOT be counted.
    vendor = tmp_path / ".venv" / "lib" / "site-packages"
    vendor.mkdir(parents=True)
    huge = "def monster():\n" + "".join(
        f"    if x{i}:\n        pass\n" for i in range(500)
    )
    (vendor / "huge.py").write_text(huge)

    metrics, _ = analyze_project(tmp_path)

    # Without the exclusion this would be ~501; the real source maxes at 2.
    assert metrics.max_cyclomatic_complexity < 10
    # And it stays within the NUMERIC(5, 2) column bound.
    assert metrics.max_cyclomatic_complexity < 1000
