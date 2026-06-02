"""Static code analysis for design friction detection."""

import ast
import hashlib
import re
from pathlib import Path

from studio.friction.contract import CodeQualityMetrics, FrictionReport, severity_from_score


# Directories that hold third-party / generated code, not the project's own source.
# Scanning them (e.g. a project-local .venv) produces wildly inflated metrics —
# a single vendored file overflowed slices.cyclomatic_complexity NUMERIC(5,2).
_VENDORED_DIRS = {
    ".venv", "venv", "env", ".env", "node_modules", ".git", "__pycache__",
    "site-packages", "build", "dist", ".tox", ".mypy_cache", ".pytest_cache",
    ".ruff_cache",
}

_DECISION_KEYWORDS = r"\b(if|elif|for|while|except|with|and|or|assert)\b"


def _is_vendored(path: Path) -> bool:
    """True if any path segment is a vendored/generated dir (or an egg-info)."""
    return any(
        part in _VENDORED_DIRS or part.endswith(".egg-info") for part in path.parts
    )


def _cyclomatic_complexity(source: str) -> int:
    """Maximum McCabe cyclomatic complexity across the functions in a module.

    Complexity is per-function (1 + decision points); we return the worst
    function's score, which is the meaningful signal. Counting decision points
    across an entire file conflates unrelated functions and inflates the value.
    Falls back to a module-wide keyword count if the source can't be parsed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return len(re.findall(_DECISION_KEYWORDS, source)) + 1

    decision_nodes = (
        ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
        ast.With, ast.AsyncWith, ast.IfExp, ast.comprehension, ast.Assert,
    )
    functions = [
        n for n in ast.walk(tree)
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    ]
    if not functions:
        return len(re.findall(_DECISION_KEYWORDS, source)) + 1

    max_complexity = 1
    for func in functions:
        complexity = 1
        for node in ast.walk(func):
            if isinstance(node, decision_nodes):
                complexity += 1
            elif isinstance(node, ast.BoolOp):
                complexity += len(node.values) - 1
        max_complexity = max(max_complexity, complexity)
    return max_complexity


def _count_imports(source: str, module_prefix: str) -> int:
    """Count imports crossing a module boundary."""
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return 0
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            if isinstance(node, ast.ImportFrom) and node.module:
                if node.module.startswith(module_prefix):
                    count += 1
    return count


def _find_duplicate_blocks(sources: dict[str, str], min_lines: int = 6) -> list[tuple[str, str, int]]:
    """Find duplicate code blocks across files. Returns list of (file1, file2, line_count)."""
    duplicates = []
    hashes: dict[str, tuple[str, int]] = {}

    for path, source in sources.items():
        lines = source.splitlines()
        for i in range(len(lines) - min_lines + 1):
            block = "\n".join(lines[i : i + min_lines]).strip()
            if len(block) < 50:
                continue
            h = hashlib.md5(block.encode()).hexdigest()
            if h in hashes:
                other_path, _ = hashes[h]
                duplicates.append((path, other_path, min_lines))
            else:
                hashes[h] = (path, i)

    return duplicates


def _count_mock_usage(source: str) -> int:
    """Count mock/patch usage as a proxy for testability friction."""
    return len(re.findall(r"\b(mock|Mock|patch|MagicMock|monkeypatch)\b", source))


def analyze_project(project_path: Path) -> tuple[CodeQualityMetrics, list[FrictionReport]]:
    """Run static analysis on a project directory and return metrics + friction reports."""
    py_files = [f for f in project_path.rglob("*.py") if not _is_vendored(f)]
    test_files = [f for f in py_files if "test" in f.name]
    src_files = [f for f in py_files if "test" not in f.name and f.name != "conftest.py"]

    sources: dict[str, str] = {}
    for f in py_files:
        try:
            sources[str(f)] = f.read_text()
        except Exception:
            pass

    friction_reports: list[FrictionReport] = []

    # === Complexity ===
    max_complexity = 0
    worst_file = ""
    for path, src in sources.items():
        if "test" in path:
            continue
        complexity = _cyclomatic_complexity(src)
        if complexity > max_complexity:
            max_complexity = complexity
            worst_file = path

    complexity_score = min(max_complexity / 10.0, 10.0)
    if complexity_score > 2.0:
        friction_reports.append(FrictionReport(
            severity=severity_from_score(complexity_score),
            category="complexity",
            description=f"Cyclomatic complexity estimated at {max_complexity} in {Path(worst_file).name}",
            code_location=worst_file,
            friction_score=complexity_score,
            suggested_design_change=(
                "Decompose the module into smaller responsibilities. "
                "Consider introducing a state machine or strategy pattern."
            ),
        ))

    # === Duplication ===
    dupes = _find_duplicate_blocks(
        {p: s for p, s in sources.items() if "test" not in p}
    )
    total_src_lines = sum(len(s.splitlines()) for p, s in sources.items() if "test" not in p)
    dup_lines = len(dupes) * 6
    dup_pct = (dup_lines / max(total_src_lines, 1)) * 100
    dup_score = min(dup_pct / 5.0, 10.0)

    if dup_score > 2.0:
        friction_reports.append(FrictionReport(
            severity=severity_from_score(dup_score),
            category="duplication",
            description=f"{len(dupes)} duplicate code block(s) detected (≥6 lines each)",
            code_location=dupes[0][0] if dupes else "",
            friction_score=dup_score,
            suggested_design_change=(
                "Extract shared logic into a protocol or base class. "
                "The design should define the shared abstraction explicitly."
            ),
        ))

    # === Testability ===
    total_mock_calls = sum(_count_mock_usage(sources.get(str(f), "")) for f in test_files)
    tests_count = len(test_files)
    # Score: more than 3 mocks per test file = friction
    mocks_per_test = total_mock_calls / max(tests_count, 1)
    test_score = min(mocks_per_test / 3.0 * 10.0, 10.0)

    if test_score > 3.0:
        friction_reports.append(FrictionReport(
            severity=severity_from_score(test_score),
            category="testability",
            description=(
                f"High mock usage: ~{mocks_per_test:.1f} mock calls per test file "
                "suggests units cannot be isolated"
            ),
            code_location=str(test_files[0]) if test_files else "",
            friction_score=test_score,
            suggested_design_change=(
                "Extract interfaces (Protocols) at module boundaries. "
                "Add dependency injection points so units can be tested with fakes."
            ),
        ))

    # === Coupling ===
    coupling_violations = 0
    for path, src in sources.items():
        if "test" in path:
            continue
        # Heuristic: cross-imports between non-adjacent modules suggest coupling
        cross = _count_imports(src, "")
        if cross > 5:
            coupling_violations += 1

    coupling_score = min(coupling_violations * 2.0, 10.0)
    if coupling_score > 2.0:
        friction_reports.append(FrictionReport(
            severity=severity_from_score(coupling_score),
            category="coupling",
            description=f"{coupling_violations} module(s) with excessive cross-module imports",
            code_location=worst_file,
            friction_score=coupling_score,
            suggested_design_change=(
                "Introduce an anti-corruption layer or event boundary. "
                "Modules should depend on abstractions (Protocols), not concrete implementations."
            ),
        ))

    metrics = CodeQualityMetrics(
        coverage_pct=0.0,  # filled in by verification runner
        max_cyclomatic_complexity=float(max_complexity),
        coupling_score=coupling_score,
        duplication_pct=dup_pct,
        tests_count=tests_count,
        tests_passing=0,  # filled in by verification runner
    )

    return metrics, friction_reports
