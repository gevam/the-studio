#!/bin/sh
# Verification sandbox entrypoint.
# Runs build, test, lint on /project and prints a JSON result to stdout.
# Exit 0 = all checks passed; exit 1 = at least one check failed.

set -e

BUILD_PASSED=true
TEST_PASSED=true
LINT_PASSED=true
BUILD_OUTPUT=""
TEST_OUTPUT=""
LINT_OUTPUT=""

echo "=== STUDIO VERIFICATION SANDBOX ===" >&2

# Build check
echo "[build] Running..." >&2
if [ -f /project/Makefile ] && grep -q "^build:" /project/Makefile 2>/dev/null; then
    BUILD_OUTPUT=$(cd /project && make build 2>&1) || BUILD_PASSED=false
elif [ -f /project/setup.py ] || [ -f /project/pyproject.toml ]; then
    BUILD_OUTPUT=$(cd /project && python -m py_compile $(find . -name "*.py" | head -50) 2>&1) || BUILD_PASSED=false
else
    BUILD_OUTPUT="BUILD OK (no build step detected)"
    echo "$BUILD_OUTPUT" >&2
fi

# Test check
echo "[test] Running..." >&2
if [ -f /project/pyproject.toml ] && command -v pytest >/dev/null 2>&1; then
    TEST_OUTPUT=$(cd /project && python -m pytest --tb=short -q 2>&1) || TEST_PASSED=false
elif [ -d /project/tests ] || [ -d /project/test ]; then
    TEST_OUTPUT=$(cd /project && python -m pytest --tb=short -q 2>&1) || TEST_PASSED=false
else
    TEST_OUTPUT="TEST OK (no test suite detected)"
    echo "$TEST_OUTPUT" >&2
fi

# Lint check
echo "[lint] Running..." >&2
if command -v ruff >/dev/null 2>&1 && [ -f /project/pyproject.toml ]; then
    LINT_OUTPUT=$(cd /project && ruff check . 2>&1) || LINT_PASSED=false
else
    LINT_OUTPUT="LINT OK (no linter configured)"
    echo "$LINT_OUTPUT" >&2
fi

# Determine overall pass/fail
PASSED=true
if [ "$BUILD_PASSED" = "false" ] || [ "$TEST_PASSED" = "false" ] || [ "$LINT_PASSED" = "false" ]; then
    PASSED=false
fi

# Emit structured JSON result
cat <<EOF
{
  "passed": $PASSED,
  "build_passed": $BUILD_PASSED,
  "test_passed": $TEST_PASSED,
  "lint_passed": $LINT_PASSED,
  "build_output": $(echo "$BUILD_OUTPUT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))"),
  "test_output": $(echo "$TEST_OUTPUT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))"),
  "lint_output": $(echo "$LINT_OUTPUT" | python3 -c "import sys,json; print(json.dumps(sys.stdin.read()))")
}
EOF

if [ "$PASSED" = "false" ]; then
    exit 1
fi
exit 0
