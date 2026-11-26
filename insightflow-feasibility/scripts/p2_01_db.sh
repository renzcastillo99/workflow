#!/usr/bin/env bash
# Serving layer for the portal: schemas live/staging, INGEST role (writes ONLY there), RO role reads live.
set -euo pipefail
cd "$(dirname "$0")/.."; set -a; . ./.env; set +a
PSQL="docker exec -i if-data-pg psql -v ON_ERROR_STOP=1 -U insightflow_admin -d clientdata"
echo "DO \$\$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='insightflow_ingest') THEN CREATE ROLE insightflow_ingest LOGIN; END IF; END \$\$; ALTER ROLE insightflow_ingest WITH LOGIN PASSWORD :'pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;" | $PSQL -v pw="$INGEST_PW"
$PSQL <<'SQL'
DROP SCHEMA IF EXISTS live CASCADE; DROP SCHEMA IF EXISTS staging CASCADE;
CREATE SCHEMA live AUTHORIZATION insightflow_ingest;
CREATE SCHEMA staging AUTHORIZATION insightflow_ingest;
REVOKE ALL ON SCHEMA live, staging FROM PUBLIC;
GRANT CONNECT ON DATABASE clientdata TO insightflow_ingest;
REVOKE CREATE ON SCHEMA public FROM insightflow_ingest;
GRANT USAGE ON SCHEMA live TO insightflow_ro;                       -- BI engine can read live ONLY (never staging)
ALTER DEFAULT PRIVILEGES FOR ROLE insightflow_ingest IN SCHEMA live GRANT SELECT ON TABLES TO insightflow_ro;
CREATE TABLE live.transactions (transaction_id text PRIMARY KEY, date date NOT NULL, branch text NOT NULL, revenue numeric(14,2) NOT NULL, cost numeric(14,2) NOT NULL);
ALTER TABLE live.transactions OWNER TO insightflow_ingest;
INSERT INTO live.transactions SELECT * FROM bench_5m.transactions WHERE transaction_id <= 'T0020000';   -- initial 20,000-row snapshot
CREATE INDEX ON live.transactions (date); CREATE INDEX ON live.transactions (branch);
GRANT SELECT ON live.transactions TO insightflow_ro; ANALYZE live.transactions;
SQL
$PSQL -At -c "select 'live rows', count(*) from live.transactions"
SQL_CHECK="select has_schema_privilege('insightflow_ro','staging','USAGE'), has_schema_privilege('insightflow_ingest','bench_1m','USAGE'), has_table_privilege('insightflow_ro','live.transactions','SELECT')"
$PSQL -At -c "$SQL_CHECK"
