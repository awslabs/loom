# Project Steering

**Documentation and fork policy live under `local-runtime/docs/`.** Do not
duplicate that content here.

## Required reading (agents)

1. [`local-runtime/docs/README.md`](local-runtime/docs/README.md) — docs hub
2. [`local-runtime/docs/guide/rules.md`](local-runtime/docs/guide/rules.md) — Core vs extension
3. Task guides as needed:
   - [`guide/getting-started.md`](local-runtime/docs/guide/getting-started.md)
   - [`guide/development.md`](local-runtime/docs/guide/development.md)
   - [`guide/mcp-hub.md`](local-runtime/docs/guide/mcp-hub.md)
   - [`guide/upstream-sync.md`](local-runtime/docs/guide/upstream-sync.md)
4. Core path changes → log in
   [`local-runtime/docs/CHANGELOG-LOOM-FORK.md`](local-runtime/docs/CHANGELOG-LOOM-FORK.md)

Cursor uses the same hub via `.cursor/rules/prefer-local-runtime-extension.mdc`
(pointer only). If a pointer and `local-runtime/docs/` disagree, **the docs win**.

**Hard gate:** do not change Loom core without explicit Dev authorization; see
[`guide/rules.md`](local-runtime/docs/guide/rules.md). Do not refactor unless
asked; log ideas in
[`backlog/refactoring.md`](local-runtime/docs/backlog/refactoring.md).
Keep [`guide/architecture.md`](local-runtime/docs/guide/architecture.md) in
sync when architecture changes.
