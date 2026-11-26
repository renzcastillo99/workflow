#!/usr/bin/env python3
"""Source-of-truth verification: Postgres (read-only role) vs independent Decimal expectations; TC-04 at DB level."""
import json
from decimal import Decimal
from common import *
ev = Evidence("source_verification")
KPI = "SELECT sum(revenue), sum(revenue-cost), CASE WHEN sum(revenue)=0 THEN NULL ELSE round(sum(revenue-cost)/sum(revenue),6) END, count(DISTINCT transaction_id) FROM {s}.transactions"
for s in ["fixture", "fixture_zero", "bench_100k", "bench_500k", "bench_1m", "bench_5m"]:
    rc, out, err = psql(KPI.format(s=s))
    rev, gp, m, n = out.split("|")
    exp = EXPECTED[s]["all"]
    ok = (Decimal(rev) == Decimal(exp["revenue"]) and Decimal(gp) == Decimal(exp["gross_profit"]) and
          ((m == "" and exp["margin"] is None) or (m != "" and Decimal(m) == Decimal(exp["margin"]))) and int(n) == exp["transaction_count"])
    ev.record("TC-05", f"{s} DB totals == independent Decimal totals", exp, {"rev": rev, "gp": gp, "margin": m or None, "n": n}, ok)
# TC-04 (database level): read works, every write form is denied for the BI service account
for label, sql in [("INSERT", "INSERT INTO fixture.transactions VALUES ('X','2025-01-01','A',1,1)"),
                   ("UPDATE", "UPDATE fixture.transactions SET revenue=0"),
                   ("DELETE", "DELETE FROM fixture.transactions"),
                   ("DROP", "DROP TABLE fixture.transactions"),
                   ("CREATE", "CREATE TABLE public.x(i int)"),
                   ("TRUNCATE", "TRUNCATE fixture.transactions")]:
    rc, out, err = psql(sql)
    ev.record("TC-04", f"read-only role: {label} denied", "error (denied)", err.splitlines()[0] if err else out, rc != 0 and ("denied" in err or "read-only" in err))
rc, out, err = psql("SELECT count(*) FROM fixture.transactions", role="ro")
ev.record("TC-04", "read-only role: SELECT works", "2", out, out == "2")
rc, out, err = psql("SELECT count(*) FROM fixture.transactions", role="admin")
ev.record("TC-04", "admin sanity: fixture untouched after write attempts", "2", out, out == "2")
# Layer 2 test: even if the session-level read-only flag is switched off by the role itself, GRANTs still deny writes.
import subprocess
pw = ENV["DATA_PG_RO_PASSWORD"]
for label, stmt in [("INSERT", "INSERT INTO fixture.transactions VALUES ('X','2025-01-01','A',1,1);"), ("UPDATE", "UPDATE fixture.transactions SET revenue=0;"),
                    ("DROP", "DROP TABLE fixture.transactions;"), ("CREATE", "CREATE TABLE public.x(i int);")]:
    p = subprocess.run(["docker","exec","-i","-e",f"PGPASSWORD={pw}","if-data-pg","psql","-h","127.0.0.1","-U","insightflow_ro","-d","clientdata","-At"],
                       input=f"SET default_transaction_read_only=off;\n{stmt}\n", capture_output=True, text=True)
    msg = [l for l in p.stderr.splitlines() if "ERROR" in l]
    ev.record("TC-04", f"GRANT layer alone (session flag overridden): {label} denied", "permission denied / must be owner", msg[0] if msg else p.stdout, bool(msg) and ("permission denied" in msg[0] or "must be owner" in msg[0]))
ev.save()
