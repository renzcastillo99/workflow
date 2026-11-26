#!/usr/bin/env python3
"""Reads live.transactions as the BI read-only role every ~15 ms for N seconds and reports every distinct (count,revenue) pair + errors.
Used to prove that a publish is ATOMIC: readers only ever see the old snapshot or the new one, never a partial/missing table."""
import sys, time, json, psycopg
sys.path.insert(0, ".")
from common import ENV
dur = float(sys.argv[1]); seen = {}; errors = []; n = 0
dsn = f"host=127.0.0.1 port=15432 dbname=clientdata user=insightflow_ro password={ENV['DATA_PG_RO_PASSWORD']}"
t_end = time.time() + dur
with psycopg.connect(dsn, autocommit=True) as c:
    while time.time() < t_end:
        try:
            cnt, rev = c.execute("SELECT count(*), sum(revenue) FROM live.transactions").fetchone(); k = f"{cnt}|{rev}"; seen[k] = seen.get(k, 0) + 1
        except Exception as e: errors.append(type(e).__name__ + ": " + str(e)[:80])
        n += 1; time.sleep(0.015)
print(json.dumps({"reads": n, "distinct_states": seen, "errors": errors[:5], "error_count": len(errors)}))
