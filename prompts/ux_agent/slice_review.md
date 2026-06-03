# UX Review — Built Slice

Review this built slice against the experience metric, from the customer's perspective.

**Project:** {{project_name}}
**Design digest:** {{design_digest}}
**Experience metric:** {{experience_metric}}
**Slice:** {{slice_name}} — {{slice_description}}
**Built artifacts (entry points / interfaces):**
{{slice_artifacts}}
**Prior UX issues:**
{{prior_issues}}

Judge:
1. Does the slice **meet the experience metric**? Score 0–10.
2. Are flows simple and consistent? Any missing error states or confusing output?
3. Accessibility / i18n / RTL concerns for what was built?

Set `needs_design_revision = true` only if a UX problem is rooted in the design (not a
build detail), with concrete `revision_suggestions`. Return the structured UXReview.
