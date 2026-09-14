-- LOCAL DEVELOPMENT ONLY. Runs once on first postgres volume init.
-- Hub clients/grants live in a dedicated database (not Loom ORM / not Keycloak).

CREATE ROLE mcp_hub WITH LOGIN PASSWORD 'mcp-hub-local-dev';
CREATE DATABASE mcp_hub OWNER mcp_hub;

\connect mcp_hub
GRANT ALL ON SCHEMA public TO mcp_hub;
