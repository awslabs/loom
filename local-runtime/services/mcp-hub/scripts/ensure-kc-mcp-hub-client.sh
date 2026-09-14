#!/usr/bin/env bash
# Ensure Keycloak realm `loom` has public client loom-mcp-hub (ADR 0011).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
JSON="${ROOT}/loom-mcp-hub-client.json"
KCADM=(docker exec -i loom-keycloak-1 /opt/keycloak/bin/kcadm.sh)

"${KCADM[@]}" config credentials \
  --server http://localhost:8080 --realm master --user admin --password admin

CID=$("${KCADM[@]}" get clients -r loom -q clientId=loom-mcp-hub \
  --fields id --format csv --noquotes | head -1 | tr -d '\r')

if [[ -n "${CID}" ]]; then
  echo "Deleting incomplete client ${CID}"
  "${KCADM[@]}" delete "clients/${CID}" -r loom
fi

echo "Creating loom-mcp-hub from ${JSON}"
docker exec -i loom-keycloak-1 /opt/keycloak/bin/kcadm.sh create clients -r loom -f - < "${JSON}"

CID=$("${KCADM[@]}" get clients -r loom -q clientId=loom-mcp-hub \
  --fields id --format csv --noquotes | head -1 | tr -d '\r')
echo "client id=${CID}"

"${KCADM[@]}" get "clients/${CID}" -r loom \
  --fields clientId,name,publicClient,standardFlowEnabled,redirectUris
"${KCADM[@]}" get "clients/${CID}/protocol-mappers/models" -r loom --fields name,protocolMapper
