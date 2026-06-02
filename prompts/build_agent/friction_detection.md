# Build Agent — Friction Detection Analysis

## Context

Analyze the code you just built and identify design friction.

**Project path:** {{project_path}}
**Files built:** {{files_built}}
**Design digest:** {{design_digest}}

## Friction Categories to Check

### Testability (category: "testability")
- Can each module be tested in isolation?
- Are dependencies injected or hardcoded?
- How many external dependencies need mocking per test?
- Are there globals or singletons that make tests order-dependent?

Score: 0 (perfect isolation) → 10 (impossible to test without full stack)

### Coupling (category: "coupling")
- Do modules import across stated boundaries?
- Are there circular imports?
- Does a module know too much about another's internals?

Score: 0 (clean boundaries) → 10 (everything depends on everything)

### Complexity (category: "complexity")
- What is the highest cyclomatic complexity in any function?
- Are there functions longer than 30 lines?
- Are there more than 3 levels of nesting?

Score: max_cyclomatic_complexity / 10 (capped at 10)

### Duplication (category: "duplication")
- Are there blocks of ≥6 lines that appear more than once (with minor variation)?
- Is there structural duplication (same pattern repeated in different files)?

Score: % of duplicate lines / 10

### Workarounds (category: "workaround")
- Did you have to write code that felt "wrong" to make something work?
- Are there comments like "TODO: this should be in X", "hack", "workaround"?
- Did you have to violate a design boundary to get something to work?

Score: 0 (clean) → 10 (extensive workarounds)

## Output

For each friction item with friction_score > 2.0, output a FrictionReport.
Output as JSON array. No markdown fences.
