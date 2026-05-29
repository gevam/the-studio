"""Static code analysis for design friction detection."""

import ast
import hashlib
import re
from pathlib import Path

from studio.friction.contract import CodeQualityMetrics, FrictionReport, severity_from_score


def _cyclomatic_complexity(source: str) -> int:
    """Estimate cyclomatic complexity by counting decision points."""
    keywords = r"\b(if|elif|else|for|while|try|except|finally|with|and|or|assert)\b"
    return len(re.findall(keywords, source)) + 1


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
    py_files = list(project_path.rglob("*.py"))
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
