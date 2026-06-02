# Design Agent — Friction Revision Task

## Context

The Build agent encountered **design friction** while building the walking skeleton. This friction is evidence that the current design has a flaw — the code is telling you something.

**Current design digest:**
{{design_digest}}

**Friction items requiring design revision:**
{{friction_items}}

**Iteration:** {{iteration}}

## Task

Revise the Living Design to eliminate the root cause of each friction item.

Key rules:
- **Do not patch the symptom** — find the design flaw that forced the workaround, coupling, or complexity
- **Revise the interface or boundary**, not the implementation detail
- **Link each revision** to the friction item(s) that triggered it
- **Update the digest** to reflect the revised design
- **Add an ADR** for each significant structural change
- Mark resolved friction items with `resolved_by_design_change: true` in your response

For each friction category, the typical design fix is:
- `testability` → extract interfaces, add dependency injection points, split responsibilities
- `coupling` → introduce an anti-corruption layer, protocol, or event boundary
- `complexity` → decompose the module, introduce a state machine or strategy pattern
- `duplication` → extract shared abstract interface, introduce a base protocol
- `workaround` → redesign the data model or interface the code was working around

## Output

Output raw JSON with two fields:
```
{
  "revised_design": <full LivingDesign JSON>,
  "revision_summary": {
    "sections_changed": ["list of section IDs"],
    "friction_resolved": ["list of friction item IDs"],
    "decisions_added": ["list of new ADR IDs"]
  }
}
```
