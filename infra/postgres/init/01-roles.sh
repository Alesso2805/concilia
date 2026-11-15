#!/bin/sh
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  -v owner_password="$CONCILIA_OWNER_PASSWORD" \
  -v app_password="$CONCILIA_APP_PASSWORD" \
  -v worker_password="$CONCILIA_WORKER_PASSWORD" \
  -v backup_password="$CONCILIA_BACKUP_PASSWORD" <<'SQL'
CREATE ROLE concilia_owner LOGIN BYPASSRLS PASSWORD :'owner_password';
CREATE ROLE concilia_app LOGIN PASSWORD :'app_password';
CREATE ROLE concilia_worker LOGIN PASSWORD :'worker_password';
CREATE ROLE concilia_backup LOGIN BYPASSRLS PASSWORD :'backup_password';
CREATE DATABASE concilia OWNER concilia_owner;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname concilia <<'SQL'
REVOKE ALL ON DATABASE concilia FROM PUBLIC;
GRANT CONNECT ON DATABASE concilia TO concilia_app, concilia_worker, concilia_backup;
ALTER SCHEMA public OWNER TO concilia_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO concilia_app, concilia_worker, concilia_backup;
SQL
