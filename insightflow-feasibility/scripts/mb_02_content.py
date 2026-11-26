#!/usr/bin/env python3
"""Step 2: collections + KPI/trend/branch/table cards + one filtered dashboard per dataset (native MBQL, no SQL)."""
from common import *; from mbapi import MB
import json
mb = MB(); mb.token = mb.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"])
st = json.load(open(ROOT / "evidence/mb_state.json")); DB = st["db_id"]
def coll(name):
    c, items, _ = mb.call("GET", "/api/collection")
    for i in items:
        if i["name"] == name and not i.get("archived"): return i["id"]
    return mb.call("POST", "/api/collection", {"name": name})[1]["id"]
COLL = {"Sales Reports": coll("Sales Reports"), "Finance Reports": coll("Finance Reports"), "Benchmarks": coll("Benchmarks")}
PLAN = [("fixture", "Sales Reports"), ("fixture_zero", "Finance Reports")] + [(s, "Benchmarks") for s in ["bench_100k", "bench_500k", "bench_1m", "bench_5m"]]
out = st.get("content", {})
for schema, cname in PLAN:
    tid = st["tables"][schema]
    c, md, _ = mb.call("GET", f"/api/table/{tid}/query_metadata"); F = {f["name"]: f["id"] for f in md["fields"]}
    f = lambda n, o=None: ["field", F[n], o]
    rev, cost = f("revenue"), f("cost")
    aggs = {"Revenue": ["sum", rev], "Gross profit": ["sum", ["-", rev, cost]],
            "Margin": ["/", ["sum", ["-", rev, cost]], ["sum", rev]], "Transactions": ["distinct", f("transaction_id")]}
    cards = []
    def mk(name, query, display, viz=None):
        r = mb.call("POST", "/api/card", {"name": f"{schema}: {name}", "display": display, "collection_id": COLL[cname],
            "visualization_settings": viz or {}, "dataset_query": {"database": DB, "type": "query", "query": {"source-table": tid, **query}}})
        assert r[0] == 200, r; return r[1]["id"]
    ids = {}
    for k, a in aggs.items():
        ids[k] = mk(k, {"aggregation": [a]}, "scalar", {"scalar.field": None} if k != "Margin" else {"column_settings": {'["name","expression"]': {"number_style": "percent", "decimals": 2}}})
    ids["Trend"] = mk("Revenue by month", {"aggregation": [aggs["Revenue"]], "breakout": [f("date", {"temporal-unit": "month"})]}, "line")
    ids["Branch"] = mk("Revenue by branch", {"aggregation": [aggs["Revenue"]], "breakout": [f("branch")]}, "bar")
    ids["Table"] = mk("Branch totals", {"aggregation": list(aggs.values()), "breakout": [f("branch")], "order-by": [["asc", f("branch")]]}, "table")
    params = [{"id": "date", "name": "Date", "slug": "date", "type": "date/all-options"},
              {"id": "branch", "name": "Branch", "slug": "branch", "type": "string/="}]
    def mapping(cid): return [{"parameter_id": "date", "card_id": cid, "target": ["dimension", ["field", F["date"], {"base-type": "type/Date"}]]},
                              {"parameter_id": "branch", "card_id": cid, "target": ["dimension", ["field", F["branch"], {"base-type": "type/Text"}]]}]
    layout = [("Revenue", 0, 0, 6, 3), ("Gross profit", 0, 6, 6, 3), ("Margin", 0, 12, 6, 3), ("Transactions", 0, 18, 6, 3),
              ("Trend", 3, 0, 12, 6), ("Branch", 3, 12, 12, 6), ("Table", 9, 0, 24, 6)]
    r = mb.call("POST", "/api/dashboard", {"name": f"Sales report - {schema}", "collection_id": COLL[cname], "parameters": params})
    assert r[0] == 200, r; did = r[1]["id"]
    dcs = [{"id": -(i + 1), "card_id": ids[k], "row": row, "col": col, "size_x": sx, "size_y": sy, "parameter_mappings": mapping(ids[k]), "visualization_settings": {}}
           for i, (k, row, col, sx, sy) in enumerate(layout)]
    r = mb.call("PUT", f"/api/dashboard/{did}", {"dashcards": dcs, "parameters": params}); assert r[0] == 200, r
    c, dash, _ = mb.call("GET", f"/api/dashboard/{did}")
    out[schema] = {"dashboard": did, "cards": ids, "dashcards": {k: dc["id"] for dc in dash["dashcards"] for k, v in ids.items() if dc["card_id"] == v}, "fields": F, "collection": cname}
    print(schema, "dashboard", did, "cards", len(dash["dashcards"]))
st["content"] = out; st["collections"] = COLL
json.dump(st, open(ROOT / "evidence/mb_state.json", "w"), indent=1)
