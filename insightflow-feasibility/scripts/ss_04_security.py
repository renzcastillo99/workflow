#!/usr/bin/env python3
"""TC-06/07/11/12 on Superset: stock Gamma baseline vs minimal custom roles + DASHBOARD_RBAC + RLS; revocation."""
from common import *; from ssapi import SS
import json, sys
from decimal import Decimal
admin = SS(); assert admin.login("admin", ENV["SS_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/ss_state.json")); ev = Evidence("superset_security")
PW = ENV["SS_VIEWER_PASSWORD"]; D, CH, DS = st["dashboards"], st["charts"], st["datasets"]
def perm_map():
    m, page = {}, 0
    while True:
        c, d, _ = admin.call("GET", f"/api/v1/security/permissions-resources/?q=(page:{page},page_size:100)")
        for r in d["result"]: m[(r["permission"]["name"], r["view_menu"]["name"])] = r["id"]
        if (page + 1) * 100 >= d["count"]: return m
        page += 1
def ensure_role(name):
    c, d, _ = admin.call("GET", "/api/v1/security/roles/search/")
    for r in d["result"]:
        if r["name"] == name: return r["id"]
    c, d, _ = admin.call("POST", "/api/v1/security/roles/", json={"name": name}); assert c in (200, 201), (c, d); return d["id"]
def ensure_user(username, role_ids):
    c, d, _ = admin.call("GET", "/api/v1/security/users/?q=(page_size:100)")
    for u in d["result"]:
        if u["username"] == username:
            admin.call("PUT", f"/api/v1/security/users/{u['id']}", json={"active": True, "roles": role_ids, "password": PW}); return u["id"]
    c, d, _ = admin.call("POST", "/api/v1/security/users/", json={"username": username, "first_name": username, "last_name": "Viewer", "email": f"{username}@feasibility.invalid", "password": PW, "active": True, "roles": role_ids}); assert c in (200, 201), (c, d); return d["id"]
def chart_data(c, schema, metrics=("revenue",), filters=None, fmt="json", form=None):
    body = {"datasource": {"id": DS[schema], "type": "table"}, "force": False, "result_format": fmt, "result_type": "full",
            "queries": [{"metrics": list(metrics), "columns": [], "filters": filters or [], "row_limit": 10, "extras": {}}]}
    if form: body["form_data"] = form
    r = c.s.post(f"{c.base}/api/v1/chart/data", json=body, headers=c.h, timeout=120)
    return r.status_code, r.text
def val(text):
    try: return json.loads(text, parse_float=Decimal)["result"][0]["data"][0]
    except Exception: return text[:120]
def probes(client, tag, expect_open):
    ok = (lambda c: c in (200, 201)) if expect_open else (lambda c: c in (401, 403, 404))
    want = "open" if expect_open else "denied"
    c, t = chart_data(client, "fixture_zero"); ev.record("TC-07", f"[{tag}] chart data on UNASSIGNED dataset (fixture_zero) via API", want, f"{c} {t[:70]}", ok(c))
    c, d, _ = client.call("GET", f"/api/v1/dashboard/{D['fixture_zero']}"); ev.record("TC-07", f"[{tag}] GET unassigned finance dashboard (direct API)", want, c, ok(c))
    c, d, _ = client.call("GET", f"/api/v1/dashboard/{D['fixture_zero']}/charts"); ev.record("TC-07", f"[{tag}] GET unassigned dashboard charts", want, c, ok(c))
    c, d, _ = client.call("GET", f"/api/v1/chart/{CH['fixture_zero']['Revenue']}"); ev.record("TC-07", f"[{tag}] GET unassigned chart", want, c, ok(c))
    c, d, _ = client.call("POST", "/api/v1/sqllab/execute/", json={"database_id": 1, "sql": "select * from fixture_zero.transactions", "runAsync": False}); ev.record("TC-07", f"[{tag}] arbitrary SQL via SQL Lab API", want, f"{c} {str(d)[:70]}", ok(c))
    c, t = chart_data(client, "bench_5m", metrics=(), filters=None); ev.record("TC-07", f"[{tag}] ad-hoc query on unassigned raw dataset (bench_5m)", want, f"{c}", ok(c))
    c, d, _ = client.call("GET", "/api/v1/dashboard/"); titles = [x["dashboard_title"] for x in d.get("result", [])] if c == 200 else []
    leak = [t for t in titles if "fixture_zero" in t]
    ev.record("TC-07", f"[{tag}] dashboard list leaks unassigned titles", "leak" if expect_open else "no unassigned titles", f"{c} {len(titles)} listed; unassigned={leak}", bool(leak) if expect_open else not leak)
    c, d, _ = client.call("GET", "/api/v1/database/"); names = [x["database_name"] for x in d.get("result", [])] if c == 200 else []
    ev.record("TC-07", f"[{tag}] GET /database/ (data source list)", "visible" if expect_open else "none listed/denied", f"{c} {names}", bool(names) if expect_open else not names)
    c, d, _ = client.call("GET", "/api/v1/dataset/"); names = [x["table_name"] + "@" + x["schema"] for x in d.get("result", [])] if c == 200 else []
    ev.record("TC-07", f"[{tag}] GET /dataset/ lists unassigned datasets", "visible" if expect_open else "none unassigned", f"{c} {names}", bool(names) if expect_open else not [n for n in names if "fixture_zero" in n or "bench" in n])
    c, d, _ = client.call("GET", "/api/v1/security/users/"); ev.record("TC-07", f"[{tag}] GET admin endpoint /security/users/", "n/a" if expect_open else "denied", c, True if expect_open else c in (401, 403))
    c, d, _ = client.call("POST", "/api/v1/security/users/", json={"username": "x"}); ev.record("TC-07", f"[{tag}] POST admin endpoint /security/users/ (create user)", "n/a" if expect_open else "denied", c, True if expect_open else c in (401, 403))
mode = sys.argv[1]
if mode == "baseline":
    gamma = ensure_role("Gamma") if False else 4
    ensure_user("viewer.gamma", [gamma]); g = SS(); assert g.login("viewer.gamma", PW)
    # stock Gamma, NO dataset grants: what does a brand-new viewer get?
    probes(g, "STOCK-GAMMA, no grants", False)
    c, d, _ = g.call("POST", "/api/v1/chart/", json={"slice_name": "viewer-made", "viz_type": "table", "datasource_id": DS["fixture"], "datasource_type": "table", "params": "{}"}); ev.record("TC-07", "[STOCK-GAMMA] viewer can create chart (can_write on Chart)", "informational", c, True, "Gamma carries can_write on Chart/Dashboard; blocked only by lack of datasource access")
    c, d, _ = g.call("GET", "/api/v1/security/permissions-resources/?q=(page_size:1)"); ev.record("TC-07", "[STOCK-GAMMA] viewer can read permission catalogue", "informational", c, True)
elif mode == "harden":
    pm = perm_map()
    ds_perm = lambda sch: [v for (p, v), i in pm.items() if p == "datasource_access" and v.endswith(f"(id:{DS[sch]})")][0]
    MIN = {"Dashboard": ["can_read"], "Chart": ["can_read"], "Dataset": ["can_read"], "Superset": ["can_dashboard", "can_log", "can_language_pack"], "CurrentUserRestApi": ["can_read"],
           "DashboardFilterStateRestApi": ["can_read", "can_write"], "DashboardPermalinkRestApi": ["can_read", "can_write"], "MenuApi": ["can_get"], "Dashboards": ["menu_access"], "Home": ["menu_access"],
           "ExploreFormDataRestApi": ["can_read"], "Datasource": ["can_get"], "Api": ["can_query_form_data", "can_time_range"], "AvailableDomains": ["can_read"], "AdvancedDataType": ["can_read"], "EmbeddedDashboard": ["can_read"], "SecurityRestApi": ["can_read"]}
    base = [pm[(p, v)] for v, ps in MIN.items() for p in ps if (p, v) in pm]
    roles = {}
    for name, schemas in [("IF_SalesViewer", ["fixture"]), ("IF_FinanceViewer", ["fixture_zero"]), ("IF_MakatiOnly", ["bench_1m"])]:
        rid = ensure_role(name); roles[name] = rid
        extra = [pm[("datasource_access", ds_perm(s))] for s in schemas]
        c, d, _ = admin.call("POST", f"/api/v1/security/roles/{rid}/permissions", json={"permission_view_menu_ids": base + extra}); print("role", name, rid, c, str(d)[:80])
    for u, r in [("viewer.sales", "IF_SalesViewer"), ("viewer.finance", "IF_FinanceViewer"), ("viewer.makati", "IF_MakatiOnly")]: ensure_user(u, [roles[r]])
    for sch, r in [("fixture", "IF_SalesViewer"), ("fixture_zero", "IF_FinanceViewer"), ("bench_1m", "IF_MakatiOnly")]:
        c, d, _ = admin.call("PUT", f"/api/v1/dashboard/{D[sch]}", json={"roles": [roles[r]]}); print("dashboard rbac", sch, c)
    # RLS (free in Superset): Makati-only role sees only Makati rows in bench_1m
    c, d, _ = admin.call("POST", "/api/v1/rowlevelsecurity/", json={"name": "makati_only", "filter_type": "Regular", "tables": [DS["bench_1m"]], "roles": [roles["IF_MakatiOnly"]], "clause": "branch = 'Makati'", "group_key": "", "description": "feasibility"}); print("RLS:", c, str(d)[:120])
    st["roles"] = roles; json.dump(st, open(ROOT / "evidence/ss_state.json", "w"), indent=1)
elif mode == "hardened":
    roles = st["roles"]; vs = SS(); assert vs.login("viewer.sales", PW)
    probes(vs, "HARDENED", False)
    c, t = chart_data(vs, "fixture"); v = val(t); ev.record("TC-07", "[HARDENED] sales viewer chart data on ASSIGNED dataset", "300.00", v, isinstance(v, dict) and Decimal(str(v["revenue"])) == Decimal("300.00"))
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}"); ev.record("TC-07", "[HARDENED] sales viewer GET ASSIGNED dashboard", "200", c, c == 200)
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}/charts"); ev.record("TC-07", "[HARDENED] sales viewer GET ASSIGNED dashboard charts", "200 with 7", f"{c} {len(d.get('result', [])) if c == 200 else d}", c == 200 and len(d["result"]) == 7)
    for what, c_ in [("create chart", vs.call("POST", "/api/v1/chart/", json={"slice_name": "x", "viz_type": "table", "datasource_id": DS["fixture"], "datasource_type": "table", "params": "{}"})[0]),
                     ("create dashboard", vs.call("POST", "/api/v1/dashboard/", json={"dashboard_title": "x"})[0]),
                     ("export dashboard", vs.call("GET", f"/api/v1/dashboard/export/?q=!({D['fixture']})")[0]),
                     ("explore_json (raw ad-hoc)", vs.call("POST", "/superset/explore_json/", json={})[0])]:
        ev.record("TC-07", f"[HARDENED] viewer attempts: {what}", "denied", c_, c_ in (401, 403, 404, 400 if False else 403))
    c, t = chart_data(vs, "fixture", fmt="csv"); ev.record("TC-07", "[HARDENED] viewer CSV export of assigned data (result_format=csv)", "denied (report export disabled by default)", f"{c} {t[:50]}", c in (401, 403))
    # RLS
    mv = SS(); assert mv.login("viewer.makati", PW); c, t = chart_data(mv, "bench_1m", ("revenue", "transactions")); v = val(t); exp = EXPECTED["bench_1m"]["per_branch"]["Makati"]
    ev.record("TC-07", "[RLS] Makati-only viewer totals == independent Makati total (server-side row filter)", f"{exp['revenue']} / {exp['transaction_count']}", v, isinstance(v, dict) and Decimal(str(v["revenue"])) == Decimal(exp["revenue"]) and v["transactions"] == exp["transaction_count"])
    c, t = chart_data(mv, "bench_1m", ("revenue",), [{"col": "branch", "op": "IN", "val": ["Cebu"]}]); v = val(t)
    ev.record("TC-07", "[RLS] Makati-only viewer tries filter branch=Cebu (bypass attempt)", "no Cebu data", v, (isinstance(v, str)) or v.get("revenue") in (None, 0))
    c, t = chart_data(mv, "fixture"); ev.record("TC-07", "[RLS] Makati viewer on other (unassigned) dataset", "denied", c, c in (401, 403))
elif mode == "revocation":
    vs = SS(); assert vs.login("viewer.sales", PW)
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}"); ev.record("TC-11", "viewer works before revocation", 200, c, c == 200)
    c, d, _ = admin.call("GET", "/api/v1/security/users/?q=(page_size:100)"); uid = [u["id"] for u in d["result"] if u["username"] == "viewer.sales"][0]
    c, d, _ = admin.call("PUT", f"/api/v1/security/users/{uid}", json={"active": False}); ev.record("TC-11", "admin deactivates user", "200", c, c == 200)
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}"); ev.record("TC-11", "revoked user's EXISTING access token on assigned dashboard", "401/403", c, c in (401, 403))
    c, t = chart_data(vs, "fixture"); ev.record("TC-11", "revoked token: data query", "401/403", c, c in (401, 403))
    t2 = SS().login("viewer.sales", PW); ev.record("TC-11", "revoked user cannot log in again", "no token", t2, t2 is None)
    admin.call("PUT", f"/api/v1/security/users/{uid}", json={"active": True, "password": PW})
    vs = SS(); assert vs.login("viewer.sales", PW); roles = st["roles"]
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}"); ev.record("TC-11", "reactivated viewer regains assigned access", 200, c, c == 200)
    c, d, _ = admin.call("PUT", f"/api/v1/security/users/{uid}", json={"roles": [roles["IF_FinanceViewer"]]}); ev.record("TC-11", "admin swaps role (Superset refuses to clear ALL roles: HTTP 400)", "200", c, c == 200)
    c, d, _ = vs.call("GET", f"/api/v1/dashboard/{D['fixture']}"); ev.record("TC-11", "assignment revoked (role swapped) -> same live token denied on old dashboard", "403/404", c, c in (401, 403, 404))
    c, t = chart_data(vs, "fixture"); ev.record("TC-11", "role swapped -> data query on old dataset denied", "401/403", c, c in (401, 403))
    admin.call("PUT", f"/api/v1/security/users/{uid}", json={"roles": [roles["IF_SalesViewer"]]})
ev.save(); (EVID / f"superset_security_{mode}.json").write_text((EVID / "superset_security.json").read_text())
