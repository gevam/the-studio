# Build Agent — Walking Skeleton Task

## Context

You are building the **walking skeleton** for a new project. The skeleton must prove the architecture works end-to-end with one thin vertical slice.

**Project:** {{project_name}}
**Design digest:** {{design_digest}}
**Project path:** {{project_path}}
**Language/stack:** {{stack}}

## Task

Build the walking skeleton using strict TDD:

1. **Initialize the project** — package structure, pyproject.toml/setup, dependencies
2. **Write the first failing test** — one end-to-end test that exercises the full stack (CLI → logic → persistence)
3. **Implement the minimal code** to make the test pass — no extra features
4. **Run tests** — confirm green
5. **Run linting** — confirm clean
6. **Commit** with message: `feat: walking skeleton — {project_name}`

## Friction Detection

After building, analyze the code for:
- **Testability**: Could you unit-test each module in isolation? If not, why?
- **Coupling**: Do modules import each other in unexpected ways?
- **Complexity**: Any function with cyclomatic complexity > 5?
- **Duplication**: Any repeated patterns > 6 lines?
- **Workarounds**: Did you write code that works around a design limitation?

Report any friction found. Do NOT fix it — report it.

## Output

Raw JSON BuildAgentOutput. No markdown fences.
