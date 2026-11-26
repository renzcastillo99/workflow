#!/usr/bin/env bash
# Loads synthetic datasets into the "client source" Postgres and creates the READ-ONLY role.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . ./.env; set +a
PSQL="docker exec -i if-data-pg psql -v ON_ERROR_STOP=1 -U insightflow_admin -d clientdata"
$PSQL -v ro_pw="$DATA_PG_RO_PASSWORD" <<'SQL'
DROP SCHEMA IF EXISTS fixture, fixture_zero, bench_100k, bench_500k, bench_1m, bench_5m CASCADE;
DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='insightflow_ro') THEN CREATE ROLE insightflow_ro LOGIN; END IF; END $$;
SQL
echo "ALTER ROLE insightflow_ro WITH LOGIN PASSWORD :'ro_pw' NOSUPERUSER NOCREATEDB NOCREATEROLE;" | $PSQL -v ro_pw="$DATA_PG_RO_PASSWORD"
$PSQL <<'SQL'
-- Source contract: explicit types, PK = transaction_id (duplicates rejected), no NULL money (never coerced to 0)
CREATE OR REPLACE FUNCTION pg_temp.mk(s text) RETURNS void LANGUAGE plpgsql AS $f$ BEGIN
  EXECUTE format('CREATE SCHEMA %I', s);
  EXECUTE format('CREATE TABLE %I.transactions (
      transaction_id text PRIMARY KEY,
      date           date          NOT NULL,
      branch         text          NOT NULL,
      revenue        numeric(14,2) NOT NULL,
      cost           numeric(14,2) NOT NULL)', s);
END $f$;
SELECT pg_temp.mk(s) FROM unnest(ARRAY['fixture','fixture_zero','bench_100k','bench_500k','bench_1m','bench_5m']) s;
SQL
for t in fixture fixture_zero bench_5m; do
  echo "loading $t ..."
  $PSQL -c "\copy $t.transactions FROM STDIN WITH (FORMAT csv, HEADER true)" < data/$t.csv
done
$PSQL <<'SQL'
INSERT INTO bench_100k.transactions SELECT * FROM bench_5m.transactions WHERE transaction_id <= 'T0100000';
INSERT INTO bench_500k.transactions SELECT * FROM bench_5m.transactions WHERE transaction_id <= 'T0500000';
INSERT INTO bench_1m.transactions   SELECT * FROM bench_5m.transactions WHERE transaction_id <= 'T1000000';
DO $$ DECLARE s text; BEGIN
 FOREACH s IN ARRAY ARRAY['fixture','fixture_zero','bench_100k','bench_500k','bench_1m','bench_5m'] LOOP
  EXECUTE format('CREATE INDEX ON %I.transactions (date)', s);
  EXECUTE format('CREATE INDEX ON %I.transactions (branch)', s);
  EXECUTE format('GRANT USAGE ON SCHEMA %I TO insightflow_ro', s);
  EXECUTE format('GRANT SELECT ON ALL TABLES IN SCHEMA %I TO insightflow_ro', s);
  EXECUTE format('ANALYZE %I.transactions', s);
 END LOOP; END $$;
GRANT CONNECT ON DATABASE clientdata TO insightflow_ro;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
-- Defense in depth: even if someone later grants write, sessions of this role are read-only
ALTER ROLE insightflow_ro SET default_transaction_read_only = on;
SQL
$PSQL -At -c "SELECT 'fixture', count(*) FROM fixture.transactions UNION ALL SELECT 'bench_100k', count(*) FROM bench_100k.transactions UNION ALL SELECT 'bench_500k', count(*) FROM bench_500k.transactions UNION ALL SELECT 'bench_1m', count(*) FROM bench_1m.transactions UNION ALL SELECT 'bench_5m', count(*) FROM bench_5m.transactions"
