-- LOCAL DEVELOPMENT ONLY. Runs once, on first initialisation of the postgres volume.
--
-- Loom and Keycloak share one PostgreSQL instance but never one database (ADR 0002):
-- Keycloak owns its schema through Liquibase and Loom manages its own DDL at startup,
-- so mixing them in a single database would let one tool see the other's tables.
--
-- The password here is a throwaway development value. It must never be reused in a
-- deployed environment, where these credentials belong in AWS Secrets Manager.

CREATE ROLE keycloak WITH LOGIN PASSWORD 'keycloak-local-dev';
CREATE DATABASE keycloak OWNER keycloak;

\connect keycloak
GRANT ALL ON SCHEMA public TO keycloak;
