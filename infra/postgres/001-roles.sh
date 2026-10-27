#!/bin/sh
# Sourced by the official entrypoint once, on an empty PostgreSQL volume.
set -eu
export MAINTAIN_SITE_A_PASSWORD="$(tr -d '\r\n' < /run/secrets/site_a_password)"
export MAINTAIN_SITE_B_PASSWORD="$(tr -d '\r\n' < /run/secrets/site_b_password)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv site_a_password MAINTAIN_SITE_A_PASSWORD
\getenv site_b_password MAINTAIN_SITE_B_PASSWORD
CREATE ROLE maintain_owner NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE maintain_runtime NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
CREATE ROLE maintain_site_a LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  IN ROLE maintain_runtime PASSWORD :'site_a_password';
CREATE ROLE maintain_site_b LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS
  IN ROLE maintain_runtime PASSWORD :'site_b_password';
REVOKE ALL ON DATABASE maintain FROM PUBLIC;
GRANT CONNECT ON DATABASE maintain TO maintain_runtime;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
CREATE SCHEMA maintain AUTHORIZATION maintain_owner;
GRANT USAGE ON SCHEMA maintain TO maintain_runtime;
SQL
unset MAINTAIN_SITE_A_PASSWORD MAINTAIN_SITE_B_PASSWORD
