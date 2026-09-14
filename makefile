.PHONY: help local.up local.down local.reset local.logs local.ps local.build local.keycloak.export local.cursor-adapter local.cursor-adapter.test local.mcp-runtime.test local.agent-runtime.test local.mcp-hub.test extension.install

COMPOSE := docker compose -f docker-compose.yml -f local-runtime/compose/overlay.yml

# Run unit + adapter test packages for a local-runtime service.
define local_service_tests
	cd local-runtime/services/$(1) && python -m unittest discover -s tests/unit -v
	cd local-runtime/services/$(1) && python -m unittest discover -s tests/adapters -v
endef

help:
	@echo "Loom — root orchestration (+ local-runtime overlay)"
	@echo ""
	@echo "  local.up               Build and start Loom + local-runtime backends"
	@echo "  local.down             Stop the stack, keeping data volumes"
	@echo "  local.reset            Stop the stack and delete its volumes (fresh database and realm)"
	@echo "  local.build            Rebuild the backend image"
	@echo "  local.logs             Follow logs from every service"
	@echo "  local.ps               Show service status"
	@echo "  local.keycloak.export  Export the running realm to etc/docker/keycloak-export/"
	@echo "  local.cursor-adapter   Rebuild/start the cursor-adapter compose service"
	@echo "  local.mcp-hub.test     Unit + adapter tests for MCP Hub"
	@echo "  local.cursor-adapter.test  Unit + adapter tests for Cursor adapter (no API key)"
	@echo "  local.mcp-runtime.test Unit + adapter tests for MCP runtime (no Azure PAT)"
	@echo "  local.agent-runtime.test Unit + adapter tests for agent runtime"
	@echo "  extension.install      Link UI plugin paths (dev hint; Vite alias resolves automatically)"
	@echo ""
	@echo "  Frontend: http://localhost:5173   Backend: http://localhost:8000/docs"
	@echo "  Keycloak: http://localhost:8081   (admin console user: admin)"
	@echo "  Extension nav: Local runtime (mcp:read)"
	@echo ""
	@echo "  Set LOOM_AWS_CREDS_DIR to your ~/.aws to exercise AWS-backed features."

local.up:
	$(COMPOSE) up --build -d --scale agent-runtime=$(or $(AGENT_RUNTIME_REPLICAS),2)
	@echo ""
	@echo "Stack starting. Keycloak's first boot creates its schema and can take a minute."
	@echo "agent-runtime replicas: $(or $(AGENT_RUNTIME_REPLICAS),2) (override with AGENT_RUNTIME_REPLICAS=N)."
	@echo "Follow progress with 'make local.logs'."

local.down:
	$(COMPOSE) down

local.reset:
	$(COMPOSE) down --volumes

local.build:
	$(COMPOSE) build backend

local.logs:
	$(COMPOSE) logs --follow

local.ps:
	$(COMPOSE) ps

# Exports outside the import directory on purpose: anything left in
# etc/docker/keycloak is imported on the next start.
local.keycloak.export:
	mkdir -p etc/docker/keycloak-export
	$(COMPOSE) exec keycloak /opt/keycloak/bin/kc.sh export \
		--realm loom --users realm_file --file /tmp/realm-loom.json
	$(COMPOSE) cp keycloak:/tmp/realm-loom.json etc/docker/keycloak-export/realm-loom.json
	@echo "Exported to etc/docker/keycloak-export/realm-loom.json — review before replacing realm-loom.json."

local.cursor-adapter:
	$(COMPOSE) up -d --build cursor-adapter

local.mcp-hub.test:
	$(call local_service_tests,mcp-hub)

local.cursor-adapter.test:
	$(call local_service_tests,cursor-adapter)

local.mcp-runtime.test:
	$(call local_service_tests,mcp-runtime)

local.agent-runtime.test:
	$(call local_service_tests,agent-runtime)

extension.install:
	@echo "UI plugin resolves via Vite alias @loom-ext/local-runtime → local-runtime/plugin"
	@echo "Docker mounts ./local-runtime/plugin at /app/extensions/local-runtime"
	@test -f local-runtime/plugin/src/register.tsx && echo "OK: plugin entry present"
