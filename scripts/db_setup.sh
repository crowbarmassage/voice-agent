#!/usr/bin/env bash
# Create the voice_agent Postgres database and user.
# Run once on a fresh machine. Requires psql access to a running Postgres.
set -euo pipefail

DB_NAME="${DB_NAME:-voice_agent}"
DB_USER="${DB_USER:-voice_agent}"
DB_PASS="${DB_PASS:-voice_agent}"

echo "Creating user ${DB_USER} and database ${DB_NAME}..."

psql -U postgres <<SQL
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = '${DB_USER}') THEN
        CREATE ROLE ${DB_USER} WITH LOGIN PASSWORD '${DB_PASS}';
    END IF;
END
\$\$;

SELECT 'CREATE DATABASE ${DB_NAME} OWNER ${DB_USER}'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = '${DB_NAME}')\gexec
SQL

echo "Running Alembic migrations..."
PYTHONPATH=src alembic upgrade head

echo "Done. Database ${DB_NAME} is ready."
