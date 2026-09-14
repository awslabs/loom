#!/usr/bin/env bash
# Hint / sanity check for the UI plugin path (ADR 0006).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PLUGIN="$ROOT/local-runtime/plugin/src/register.tsx"
if [[ ! -f "$PLUGIN" ]]; then
  echo "missing plugin entry: $PLUGIN" >&2
  exit 1
fi
echo "plugin OK: $PLUGIN"
echo "Vite alias: @loom-ext/local-runtime → local-runtime/plugin"
echo "Compose: docker compose -f docker-compose.yml -f local-runtime/compose/overlay.yml"
