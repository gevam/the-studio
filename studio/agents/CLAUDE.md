# Agents — local rules
- All agents inherit `studio.agents.base.BaseAgent`.
- I/O contracts are Pydantic models defined in this directory.
- Never inline prompts — load from `prompts/<agent>/` (see §8.2).
- Emit `agent.started` and `agent.completed` events (§7.2).
- Write an AIFeedbackRecord on every run (§8.1).

