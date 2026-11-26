#!/usr/bin/env python3
"""TC-05 / TC-08 on Superset via /api/v1/chart/data (what every chart calls) vs independent Decimal expectations."""
from common import *; from ssapi import SS
from decimal import Decimal
import json
ss = SS(); assert ss.login("admin", ENV["SS_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/ss_state.json")); ev = Evidence("superset_functional")
def q(schema, metrics, filters=None, columns=None):
    body = {"datasource": {"id": st["datasets"][schema], "type": "table"}, "force": True, "result_format": "json", "result_type": "full",
            "queries": [{"metrics": metrics, "columns": columns or [], "filters": filters or [], "row_limit": 100, "extras": {}, "orderby": []}]}
    r = ss.s.post(f"{ss.base}/api/v1/chart/data", json=body, headers=ss.h, timeout=300)
    assert r.status_code == 200, (r.status_code, r.text[:300]); return json.loads(r.text, parse_float=Decimal)["result"][0]["data"]
def kpis(schema, filters=None):
    row = q(schema, ["revenue", "gross_profit", "margin", "transactions"], filters)
    return row[0] if row else {}
def cmp(tc, label, got, exp):
    dec = lambda x: None if x is None else Decimal(str(x))
    ok = (dec(got.get("revenue")) == Decimal(exp["revenue"]) and dec(got.get("gross_profit")) == Decimal(exp["gross_profit"]) and got.get("transactions") == exp["transaction_count"]
          and ((exp["margin"] is None and got.get("margin") is None) or (exp["margin"] is not None and got.get("margin") is not None and abs(dec(got["margin"]) - Decimal(exp["margin"])) < Decimal("0.0000005"))))
    ev.record(tc, label, exp, got, ok)
cmp("TC-05", "fixture 2 rows -> 300/120/40%/2", kpis("fixture"), EXPECTED["fixture"]["all"])
cmp("TC-08", "fixture filter branch=Makati -> 100/40/40%/1", kpis("fixture", [{"col": "branch", "op": "IN", "val": ["Makati"]}]), EXPECTED["fixture"]["first_row_only"])
cmp("TC-08", "fixture filter date=2025-01-10 -> first row only", kpis("fixture", [{"col": "date", "op": "TEMPORAL_RANGE", "val": "2025-01-10 : 2025-01-11"}]), EXPECTED["fixture"]["first_row_only"])
cmp("TC-05", "fixture_zero: margin undefined (NOT 0, NOT error)", kpis("fixture_zero"), EXPECTED["fixture_zero"]["all"])
for s in ["bench_100k", "bench_500k", "bench_1m", "bench_5m"]: cmp("TC-05", f"{s} unfiltered vs independent Decimal totals", kpis(s), EXPECTED[s]["all"])
f = EXPECTED["_filter_definition"]; import datetime as dt
end = (dt.date.fromisoformat(f["date_to"]) + dt.timedelta(days=1)).isoformat()
cmp("TC-08", "bench_1m branch+date range filter vs independent Decimal", kpis("bench_1m", [{"col": "branch", "op": "IN", "val": [f["branch"]]}, {"col": "date", "op": "TEMPORAL_RANGE", "val": f"{f['date_from']} : {end}"}]), EXPECTED["bench_1m"]["filter"])
rows = q("bench_1m", ["revenue", "transactions"], None, ["branch"])
ok = len(rows) == 12 and all(Decimal(str(r["revenue"])) == Decimal(EXPECTED["bench_1m"]["per_branch"][r["branch"]]["revenue"]) and r["transactions"] == EXPECTED["bench_1m"]["per_branch"][r["branch"]]["transaction_count"] for r in rows)
ev.record("TC-05", "bench_1m branch-table: all 12 branches revenue+count exact", "12 match", f"{len(rows)} rows, match={ok}", ok)
ev.save()
