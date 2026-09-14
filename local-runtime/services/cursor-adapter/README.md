# Cursor adapter (host only)

Starts with the rest of the local stack (`docker compose up` / `make local.up`).
LiteLLM reaches it on the compose network:

```text
LiteLLM (Docker)
  → POST http://cursor-adapter:8765/v1/chat/completions
    → this container
      → cursor_sdk (+ Bridge)
        → Cursor Agent (cwd = /workspace)
```

Copy `.env.example` to `.env` at the repo root and set `CURSOR_API_KEY`.
The adapter process starts even when the key is empty; chat completions then
return 401 until you set the key and recreate the service.

Host fallback (without Compose): `CURSOR_ADAPTER_HOST=127.0.0.1 python -m cursor_adapter`.

## Package layout (hexagonal)

```text
cursor_adapter/
  domain/           # errors, translation, planner, streaming
  application/      # ports, wiring, use_cases/chat
  adapters/
    inbound/http_app.py
    outbound/{sdk_runner,memory_sessions}.py
  *.py              # compat shims
```
