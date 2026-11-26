#!/usr/bin/env python3
"""TC-05 / TC-08 on Metabase: KPI values via dashboard cards (incl. dashboard filters) vs independent Decimal expectations."""
from common import *; from mbapi import MB
from decimal import Decimal
import json
mb = MB(); mb.token = mb.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"])
st = json.load(open(ROOT / "evidence/mb_state.json")); ev = Evidence("metabase_functional")
def kpis(schema, params=None):
    s = st["content"][schema]; res = {}
    for k in ["Revenue", "Gross profit", "Margin", "Transactions"]:
        c, d, ms = mb.call("POST", f"/api/dashboard/{s['dashboard']}/dashcard/{s['dashcards'][k]}/card/{s['cards'][k]}/query", {"parameters": params or []})
        assert c in (200, 202), (c, d)
        res[k] = d["data"]["rows"][0][0] if d["data"]["rows"] else "NO-ROWS"
    return res
def cmp(tc, label, got, exp):
    dec = lambda x: None if x is None else Decimal(str(x))
    ok = (dec(got["Revenue"]) == Decimal(exp["revenue"]) and dec(got["Gross profit"]) == Decimal(exp["gross_profit"]) and got["Transactions"] == exp["transaction_count"]
          and ((exp["margin"] is None and got["Margin"] is None) or (exp["margin"] is not None and got["Margin"] is not None and abs(dec(got["Margin"]) - Decimal(exp["margin"])) < Decimal("0.0000005"))))
    ev.record(tc, label, exp, got, ok)
cmp("TC-05", "fixture 2 rows -> 300/120/40%/2", kpis("fixture"), EXPECTED["fixture"]["all"])
tf = [{"id": "branch", "type": "string/=", "value": ["Makati"], "target": ["dimension", ["field", st["content"]["fixture"]["fields"]["branch"], {"base-type": "type/Text"}]]}]
cmp("TC-08", "fixture filter branch=Makati -> 100/40/40%/1", kpis("fixture", tf), EXPECTED["fixture"]["first_row_only"])
df = [{"id": "date", "type": "date/all-options", "value": "2025-01-10", "target": ["dimension", ["field", st["content"]["fixture"]["fields"]["date"], {"base-type": "type/Date"}]]}]
cmp("TC-08", "fixture filter date=2025-01-10 -> first row only", kpis("fixture", df), EXPECTED["fixture"]["first_row_only"])
cmp("TC-05", "fixture_zero: margin undefined (NOT 0, NOT error)", kpis("fixture_zero"), EXPECTED["fixture_zero"]["all"])
for s in ["bench_100k", "bench_500k", "bench_1m", "bench_5m"]:
    cmp("TC-05", f"{s} unfiltered vs independent Decimal totals", kpis(s), EXPECTED[s]["all"])
F = st["content"]["bench_1m"]["fields"]; flt = EXPECTED["_filter_definition"]
fp = [{"id": "branch", "type": "string/=", "value": [flt["branch"]], "target": ["dimension", ["field", F["branch"], {"base-type": "type/Text"}]]},
      {"id": "date", "type": "date/all-options", "value": f"{flt['date_from']}~{flt['date_to']}", "target": ["dimension", ["field", F["date"], {"base-type": "type/Date"}]]}]
cmp("TC-08", "bench_1m branch+date range filter vs independent Decimal", kpis("bench_1m", fp), EXPECTED["bench_1m"]["filter"])
# per-branch table card vs independent per-branch expectations (1m)
s = st["content"]["bench_1m"]; c, d, _ = mb.call("POST", f"/api/dashboard/{s['dashboard']}/dashcard/{s['dashcards']['Table']}/card/{s['cards']['Table']}/query", {"parameters": []})
bad = [r[0] for r in d["data"]["rows"] if (Decimal(str(r[1])) != Decimal(EXPECTED["bench_1m"]["per_branch"][r[0]]["revenue"]) and False)]
rows = {r[0]: r for r in d["data"]["rows"]}
# per_branch expected is cumulative to 5m at snapshot time -> compare only at 1m snapshot (stored per checkpoint)
ok = all(Decimal(str(rows[b][1])) == Decimal(EXPECTED["bench_1m"]["per_branch"][b]["revenue"]) and rows[b][4] == EXPECTED["bench_1m"]["per_branch"][b]["transaction_count"] for b in rows)
ev.record("TC-05", "bench_1m branch-table card: all 12 branches revenue+count exact", "12 branches match", f"{len(rows)} branches, match={ok}", ok and len(rows) == 12)
ev.save()
