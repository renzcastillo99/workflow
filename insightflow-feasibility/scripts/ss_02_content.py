#!/usr/bin/env python3
"""Superset content: datasets+metrics, 7 charts, dashboard w/ native filters, one per dataset. No SQL needed for viewers."""
from common import *; from ssapi import SS
import json
ss = SS(); assert ss.login("admin", ENV["SS_ADMIN_PASSWORD"])
METRICS = [("revenue", "SUM(revenue)", "Revenue"), ("gross_profit", "SUM(revenue - cost)", "Gross profit"),
           ("margin", "SUM(revenue - cost) / NULLIF(SUM(revenue), 0)", "Margin"), ("transactions", "COUNT(DISTINCT transaction_id)", "Transactions")]
state = {"datasets": {}, "charts": {}, "dashboards": {}}
def must(r, what):
    assert r[0] in (200, 201), (what, r[0], str(r[1])[:400]); return r[1]
for schema in ["fixture", "fixture_zero", "bench_100k", "bench_500k", "bench_1m", "bench_5m"]:
    d = must(ss.call("POST", "/api/v1/dataset/", json={"database": 1, "schema": schema, "table_name": "transactions"}), f"dataset {schema}")
    dsid = d["id"]
    must(ss.call("PUT", f"/api/v1/dataset/{dsid}?override_columns=false", json={"metrics": [{"metric_name": n, "expression": e, "verbose_name": v} for n, e, v in METRICS]}), "metrics")
    state["datasets"][schema] = dsid
    ds = f"{dsid}__table"; ids = {}
    def chart(name, viz, params):
        p = {"datasource": ds, "viz_type": viz, "adhoc_filters": [], **params}
        r = must(ss.call("POST", "/api/v1/chart/", json={"slice_name": f"{schema}: {name}", "viz_type": viz, "datasource_id": dsid, "datasource_type": "table", "params": json.dumps(p)}), f"chart {name}")
        return r["id"]
    ids["Revenue"] = chart("Revenue", "big_number_total", {"metric": "revenue", "y_axis_format": ",.2f", "subtitle": "Revenue"})
    ids["Gross profit"] = chart("Gross profit", "big_number_total", {"metric": "gross_profit", "y_axis_format": ",.2f", "subtitle": "Gross profit"})
    ids["Margin"] = chart("Margin", "big_number_total", {"metric": "margin", "y_axis_format": ".2%", "subtitle": "Margin"})
    ids["Transactions"] = chart("Transactions", "big_number_total", {"metric": "transactions", "y_axis_format": ",d", "subtitle": "Transactions"})
    ids["Trend"] = chart("Revenue by month", "echarts_timeseries_line", {"x_axis": "date", "time_grain_sqla": "P1M", "metrics": ["revenue"], "groupby": [], "row_limit": 10000, "y_axis_format": ",.0f"})
    ids["Branch"] = chart("Revenue by branch", "echarts_timeseries_bar", {"x_axis": "branch", "metrics": ["revenue"], "groupby": [], "row_limit": 100, "y_axis_format": ",.0f", "x_axis_sort_asc": True})
    ids["Table"] = chart("Branch totals", "table", {"query_mode": "aggregate", "groupby": ["branch"], "metrics": ["revenue", "gross_profit", "margin", "transactions"], "all_columns": [], "row_limit": 1000, "order_desc": False})
    def comp(i, cid, w, h): return {"type": "CHART", "id": f"CHART-{i}", "children": [], "meta": {"chartId": cid, "width": w, "height": h, "sliceName": f"c{cid}"}}
    pos = {"DASHBOARD_VERSION_KEY": "v2", "ROOT_ID": {"type": "ROOT", "id": "ROOT_ID", "children": ["GRID_ID"]},
           "GRID_ID": {"type": "GRID", "id": "GRID_ID", "children": ["ROW-1", "ROW-2", "ROW-3"], "parents": ["ROOT_ID"]}}
    rows = {"ROW-1": [("Revenue", 3, 15), ("Gross profit", 3, 15), ("Margin", 3, 15), ("Transactions", 3, 15)], "ROW-2": [("Trend", 6, 40), ("Branch", 6, 40)], "ROW-3": [("Table", 12, 40)]}
    for rid, items in rows.items():
        pos[rid] = {"type": "ROW", "id": rid, "children": [f"CHART-{ids[k]}" for k, _, _ in items], "parents": ["ROOT_ID", "GRID_ID"], "meta": {"background": "BACKGROUND_TRANSPARENT"}}
        for k, w, h in items: pos[f"CHART-{ids[k]}"] = {**comp(ids[k], ids[k], w, h), "id": f"CHART-{ids[k]}", "parents": ["ROOT_ID", "GRID_ID", rid]}
    nf = [{"id": "NATIVE_FILTER-branch", "name": "Branch", "filterType": "filter_select", "type": "NATIVE_FILTER", "targets": [{"datasetId": dsid, "column": {"name": "branch"}}],
           "controlValues": {"multiSelect": True, "enableEmptyFilter": False, "defaultToFirstItem": False, "searchAllOptions": False, "inverseSelection": False},
           "scope": {"rootPath": ["ROOT_ID"], "excluded": []}, "cascadeParentIds": [], "defaultDataMask": {"extraFormData": {}, "filterState": {}}},
          {"id": "NATIVE_FILTER-date", "name": "Date", "filterType": "filter_time", "type": "NATIVE_FILTER", "targets": [{}], "controlValues": {},
           "scope": {"rootPath": ["ROOT_ID"], "excluded": []}, "cascadeParentIds": [], "defaultDataMask": {"extraFormData": {}, "filterState": {}}}]
    dash = must(ss.call("POST", "/api/v1/dashboard/", json={"dashboard_title": f"Sales report - {schema}", "position_json": json.dumps(pos), "json_metadata": json.dumps({"native_filter_configuration": nf, "color_scheme": ""}), "published": True}), "dashboard")
    for cid in ids.values(): must(ss.call("PUT", f"/api/v1/chart/{cid}", json={"dashboards": [dash["id"]]}), "link chart")
    state["charts"][schema] = ids; state["dashboards"][schema] = dash["id"]; print(schema, "dataset", dsid, "dashboard", dash["id"], "charts", len(ids))
json.dump(state, open(ROOT / "evidence/ss_state.json", "w"), indent=1)
