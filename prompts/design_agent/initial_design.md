# Design Agent — Initial Design Task

## Context

You are creating the initial Living Design for a new software project.

**Requirements:**
{{requirements}}

**Project name:** {{project_name}}
**Iteration:** {{iteration}}

## Task

Produce a complete `LivingDesign` JSON document for this project.

Guidelines:
- Identify 2-6 distinct module boundaries with clear responsibilities and Protocol interfaces
- Design the data model with explicit field types, nullability, and privacy classification
- Map the key user flows (even for CLI/API — there are always users)
- Define a measurable experience metric (e.g., "add a todo in ≤2 commands")
- Write at least one ADR for the most significant architectural choice
- Perform a lightweight STRIDE threat model (identify the top 3 threats)
- Plan for privacy: identify any PII and document retention + erasure
- Flag any open questions that block design decisions

## Output

Output raw JSON matching the LivingDesign schema. No markdown fences.
