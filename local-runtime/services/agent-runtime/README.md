# Agent runtime (ADR 0005) — deferred

This service is intentionally **not** implemented yet so the migration to
`local-runtime` (ADR 0006) can finish first: sidecars, compose overlay, and
the UI plugin.

When ready:

1. Implement `agent_runtime/` per specs 011–014.
2. Add the service to `compose/overlay.yml`.
3. Set `AGENT_RUNTIME_URL` on the Loom backend (BFF invoke for `source=local`).

Until then, `source=local` keeps using the in-process LiteLLM shortcut in Loom.
