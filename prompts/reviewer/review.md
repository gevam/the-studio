# Reviewer — Slice Evaluation

Evaluate this verified slice against the rubric. Deterministic checks already passed.

**Project:** {{project_name}}
**Design digest:** {{design_digest}}
**Slice:** {{slice_name}} — {{slice_description}}
**Verification:** build/tests/coverage/lint/secrets/pii/type-check all passed
({{coverage_pct}}% coverage, {{tests_run}} tests).
**Changed files:**
{{code_artifacts}}

Score each rubric criterion 0–10 with a finding and concrete evidence. Set `passed`
false only for real, evidenced problems a maintainer would block on. Return the
structured ReviewerOutput.
