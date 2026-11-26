#!/usr/bin/env python3
"""Phase 2 mini: Superset objects for the 'live' dataset, embedding for the 3 demo reports, and a LEAST-PRIVILEGE service account
(role IF_TokenMinter: can mint guest tokens + invalidate cache, nothing else)."""
from common import *; from ssapi import SS
import json
ss = SS(); assert ss.login("admin", ENV["SS_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/ss_state.json"))
def must(r, what): assert r[0] in (200, 201), (what, r[0], str(r[1])[:300]); return r[1]
METRICS = [("revenue", "SUM(revenue)", "Revenue"), ("gross_profit", "SUM(revenue - cost)", "Gross profit"), ("margin", "SUM(revenue - cost) / NULLIF(SUM(revenue), 0)", "Margin"), ("transactions", "COUNT(DISTINCT transaction_id)", "Transactions")]
if "live" not in st["datasets"]:
    dsid = must(ss.call("POST", "/api/v1/dataset/", json={"database": 1, "schema": "live", "table_name": "transactions"}), "dataset")["id"]
    must(ss.call("PUT", f"/api/v1/dataset/{dsid}?override_columns=false", json={"metrics": [{"metric_name": n, "expression": e, "verbose_name": v} for n, e, v in METRICS]}), "metrics")
    ds = f"{dsid}__table"; ids = {}
    def chart(name, viz, params):
        p = {"datasource": ds, "viz_type": viz, "adhoc_filters": [], **params}
        return must(ss.call("POST", "/api/v1/chart/", json={"slice_name": name, "viz_type": viz, "datasource_id": dsid, "datasource_type": "table", "params": json.dumps(p)}), name)["id"]
    ids["Revenue"] = chart("Revenue", "big_number_total", {"metric": "revenue", "y_axis_format": ",.2f", "subtitle": "Revenue"})
    ids["Gross profit"] = chart("Gross profit", "big_number_total", {"metric": "gross_profit", "y_axis_format": ",.2f", "subtitle": "Gross profit"})
    ids["Margin"] = chart("Margin", "big_number_total", {"metric": "margin", "y_axis_format": ".2%", "subtitle": "Margin"})
    ids["Transactions"] = chart("Transactions", "big_number_total", {"metric": "transactions", "y_axis_format": ",d", "subtitle": "Transactions"})
    ids["Trend"] = chart("Revenue by month", "echarts_timeseries_line", {"x_axis": "date", "time_grain_sqla": "P1M", "metrics": ["revenue"], "groupby": [], "row_limit": 10000, "y_axis_format": ",.0f"})
    ids["Branch"] = chart("Revenue by branch", "echarts_timeseries_bar", {"x_axis": "branch", "metrics": ["revenue"], "groupby": [], "row_limit": 100, "y_axis_format": ",.0f", "x_axis_sort_asc": True})
    ids["Table"] = chart("Branch totals", "table", {"query_mode": "aggregate", "groupby": ["branch"], "metrics": ["revenue", "gross_profit", "margin", "transactions"], "all_columns": [], "row_limit": 1000, "order_desc": False})
    comp = lambda cid, w, h, rid: {"type": "CHART", "id": f"CHART-{cid}", "children": [], "parents": ["ROOT_ID", "GRID_ID", rid], "meta": {"chartId": cid, "width": w, "height": h, "sliceName": f"c{cid}"}}
    rows = {"ROW-1": [("Revenue", 3, 15), ("Gross profit", 3, 15), ("Margin", 3, 15), ("Transactions", 3, 15)], "ROW-2": [("Trend", 6, 40), ("Branch", 6, 40)], "ROW-3": [("Table", 12, 40)]}
    pos = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]}, "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": list(rows), "parents": ["ROOT_ID"]}}
    for rid, items in rows.items():
        pos[rid] = {"type": "ROW", "id": rid, "children": [f"CHART-{ids[k]}" for k, _, _ in items], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for k, w, h in items: pos[f"CHART-{ids[k]}"] = comp(ids[k], w, h, rid)
    nf = [{"id": "NATIVE_FILTER-branch", "name": "Branch", "filterType": "filter_select", "type": "NATIVE_FILTER", "targets": [{"datasetId": dsid, "column": {"name": "branch"}}], "controlValues": {"multiSelect": True, "enableEmptyFilter": False, "defaultToFirstItem": False, "searchAllOptions": False, "inverseSelection": False}, "scope": {"rootPath": ["ROOT_ID"], "excluded": []}, "cascadeParentIds": [], "defaultDataMask": {"extraFormData": {}, "filterState": {}}},
          {"id": "NATIVE_FILTER-date", "name": "Date", "filterType": "filter_time", "type": "NATIVE_FILTER", "targets": [{}], "controlValues": {}, "scope": {"rootPath": ["ROOT_ID"], "excluded": []}, "cascadeParentIds": [], "defaultDataMask": {"extraFormData": {}, "filterState": {}}}]
    dash = must(ss.call("POST", "/api/v1/dashboard/", json={"dashboard_title": "Sales report - live", "position_json": json.dumps(pos), "json_metadata": json.dumps({"native_filter_configuration": nf, "color_scheme": ""}), "published": True}), "dashboard")
    for cid in ids.values(): must(ss.call("PUT", f"/api/v1/chart/{cid}", json={"dashboards": [dash["id"]]}), "link")
    st["datasets"]["live"], st["dashboards"]["live"], st["charts"]["live"] = dsid, dash["id"], ids
    json.dump(st, open(ROOT / "evidence/ss_state.json", "w"), indent=1)
# embedding (allowed_domains = the portal origin only)
ORIGIN = "http://127.0.0.1:9000"; emb = {}
for key in ["live", "fixture_zero", "bench_1m"]:
    emb[key] = must(ss.call("POST", f"/api/v1/dashboard/{st['dashboards'][key]}/embedded", json={"allowed_domains": [ORIGIN]}), f"embed {key}")["result"]["uuid"]
# least-privilege service account
c, d, _ = ss.call("GET", "/api/v1/security/roles/search/"); roles = {r["name"]: r["id"] for r in d["result"]}
rid = roles.get("IF_TokenMinter") or must(ss.call("POST", "/api/v1/security/roles/", json={"name": "IF_TokenMinter"}), "role")["id"]
perms = {}; page = 0
while True:
    c, d, _ = ss.call("GET", f"/api/v1/security/permissions-resources/?q=(page:{page},page_size:100)")
    for r in d["result"]: perms[(r["permission"]["name"], r["view_menu"]["name"])] = r["id"]
    if (page + 1) * 100 >= d["count"]: break
    page += 1
want = [("can_grant_guest_token", "SecurityRestApi"), ("can_invalidate", "CacheRestApi"), ("can_read", "SecurityRestApi")]   # can_read = CSRF token endpoint
print("available:", [w for w in want if w in perms], "missing:", [w for w in want if w not in perms])
must(ss.call("POST", f"/api/v1/security/roles/{rid}/permissions", json={"permission_view_menu_ids": [perms[w] for w in want if w in perms]}), "role perms")
c, d, _ = ss.call("GET", "/api/v1/security/users/?q=(page_size:100)")
if not any(u["username"] == "portal-svc" for u in d["result"]):
    must(ss.call("POST", "/api/v1/security/users/", json={"username": "portal-svc", "first_name": "Portal", "last_name": "Service", "email": "portal-svc@feasibility.invalid", "password": ENV["SVC_PASSWORD"], "active": True, "roles": [rid]}), "svc user")
else: ss.call("PUT", f"/api/v1/security/users/{[u['id'] for u in d['result'] if u['username']=='portal-svc'][0]}", json={"password": ENV["SVC_PASSWORD"], "roles": [rid]})
state = {"reports": {"sales-live": {"title": "Sales report (live data)", "uuid": emb["live"], "dashboard_id": st["dashboards"]["live"], "dataset_id": st["datasets"]["live"], "live": True},
                     "finance-check": {"title": "Finance zero-revenue check", "uuid": emb["fixture_zero"], "dashboard_id": st["dashboards"]["fixture_zero"], "dataset_id": st["datasets"]["fixture_zero"], "live": False},
                     "large-1m": {"title": "Large dataset (1M rows)", "uuid": emb["bench_1m"], "dashboard_id": st["dashboards"]["bench_1m"], "dataset_id": st["datasets"]["bench_1m"], "live": False}}}
json.dump(state, open(ROOT / "evidence/p2_state.json", "w"), indent=1); print(json.dumps({k: v["uuid"] for k, v in state["reports"].items()}))
# verify the service account really is least-privilege
sv = SS(); assert sv.login("portal-svc", ENV["SVC_PASSWORD"])
for label, m, p, b in [("mint guest token", "POST", "/api/v1/security/guest_token/", {"user": {"username": "t"}, "resources": [{"type": "dashboard", "id": emb["live"]}], "rls": []}),
                       ("list users", "GET", "/api/v1/security/users/", None), ("list databases", "GET", "/api/v1/database/", None), ("list dashboards", "GET", "/api/v1/dashboard/", None), ("SQL Lab", "POST", "/api/v1/sqllab/execute/", {"database_id": 1, "sql": "select 1"}),
                       ("invalidate cache", "POST", "/api/v1/cachekey/invalidate", {"datasource_uids": [f"{st['datasets']['live']}__table"]})]:
    c, d, _ = sv.call(m, p, json=b); print(f"  svc {label}: HTTP {c}")
