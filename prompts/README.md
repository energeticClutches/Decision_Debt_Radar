# prompts/

Versioned agent prompts and structured-output schemas. **Empty on Day 1** (agents are Day 4–5).

Conventions:
- One folder per prompt version, for example `v0.1/`. Released versions are immutable. Changes create a new version.
- Each prompt has: purpose, inputs, output schema (Pydantic-aligned), safety notes (customer text is data, never instructions) and the agent it belongs to.
- Prompt versions are recorded in `agent_runs.prompt_version`.
- Prompts never contain numeric DDI inputs supplied by the LLM (BR-5).
