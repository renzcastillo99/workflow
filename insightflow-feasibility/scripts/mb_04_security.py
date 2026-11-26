#!/usr/bin/env python3
"""TC-06/07/11/12 on Metabase OSS: default (baseline) vs hardened authorization, direct URL + API probes, revocation."""
from common import *; from mbapi import MB
import json, sys
admin = MB(); admin.token = admin.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"])
st = json.load(open(ROOT / "evidence/mb_state.json")); ev = Evidence("metabase_security")
SALES, FIN = st["content"]["fixture"], st["content"]["fixture_zero"]       # SALES in "Sales Reports", FIN in "Finance Reports"
def user(email, pw, first):
    c, us, _ = admin.call("GET", "/api/user?include_deactivated=true")
    for u in (us["data"] if isinstance(us, dict) else us):
        if u["email"] == email:
            if not u.get("is_active", True): admin.call("PUT", f"/api/user/{u['id']}/reactivate")
            admin.call("PUT", f"/api/user/{u['id']}/password", {"password": pw}); return u["id"]
    c, d, _ = admin.call("POST", "/api/user", {"first_name": first, "last_name": "Viewer", "email": email, "password": pw}); assert c == 200, d; return d["id"]
uS = user("viewer.sales@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"], "Sales")
uF = user("viewer.finance@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"], "Finance")
vs = MB(); vs.token = vs.login("viewer.sales@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"])
NATIVE = {"database": st["db_id"], "type": "native", "native": {"query": "select * from fixture_zero.transactions"}}
def probes(label, expect_open):
    """expect_open=True => baseline (we expect to document a leak); False => hardened (must be denied)."""
    ok = lambda code: (code in (200, 202)) if expect_open else (code in (401, 403, 404))
    tag = "BASELINE-DEFAULTS" if expect_open else "HARDENED"
    c, d, _ = vs.call("GET", f"/api/dashboard/{FIN['dashboard']}"); ev.record("TC-07", f"[{tag}] sales viewer GET unassigned finance dashboard (direct URL/API)", "open(200)" if expect_open else "denied", c, ok(c))
    c, d, _ = vs.call("GET", f"/api/card/{FIN['cards']['Revenue']}"); ev.record("TC-07", f"[{tag}] sales viewer GET unassigned card", "open(200)" if expect_open else "denied", c, ok(c))
    c, d, _ = vs.call("POST", f"/api/card/{FIN['cards']['Revenue']}/query"); ev.record("TC-07", f"[{tag}] sales viewer run unassigned card query", "open" if expect_open else "denied", c, ok(c))
    c, d, _ = vs.call("POST", f"/api/dashboard/{FIN['dashboard']}/dashcard/{FIN['dashcards']['Revenue']}/card/{FIN['cards']['Revenue']}/query", {"parameters": []}); ev.record("TC-07", f"[{tag}] sales viewer run unassigned dashcard query", "open" if expect_open else "denied", c, ok(c))
    c, d, _ = vs.call("POST", "/api/dataset", NATIVE); ev.record("TC-07", f"[{tag}] sales viewer arbitrary native SQL via /api/dataset", "open" if expect_open else "denied", f"{c} {str(d)[:80]}", ok(c) if expect_open else (c in (401, 403) or (c == 202 and isinstance(d, dict) and d.get("error"))) )
    mbql = {"database": st["db_id"], "type": "query", "query": {"source-table": st["tables"]["bench_5m"], "aggregation": [["count"]]}}
    c, d, _ = vs.call("POST", "/api/dataset", mbql); ev.record("TC-07", f"[{tag}] sales viewer ad-hoc query-builder query on raw table", "open" if expect_open else "denied", f"{c} {str(d)[:80]}", ok(c) if expect_open else (c in (401, 403) or (c == 202 and isinstance(d, dict) and d.get("error"))))
    c, d, _ = vs.call("GET", f"/api/dashboard/{SALES['dashboard']}"); ev.record("TC-07", f"[{tag}] sales viewer GET ASSIGNED sales dashboard", "200 (assigned must work)", c, c == 200)
    c, d, _ = vs.call("POST", f"/api/dashboard/{SALES['dashboard']}/dashcard/{SALES['dashcards']['Revenue']}/card/{SALES['cards']['Revenue']}/query", {"parameters": []})
    ev.record("TC-07", f"[{tag}] sales viewer run ASSIGNED dashcard query", "200/202 revenue 300.00", f"{c} {d['data']['rows'] if c in (200,202) and d.get('data') else d}", c in (200, 202) and d.get("data", {}).get("rows") == [[__import__('decimal').Decimal('300.00')]])
    c, d, _ = vs.call("POST", "/api/card", {"name": "viewer-made", "display": "table", "collection_id": st["collections"]["Sales Reports"], "visualization_settings": {}, "dataset_query": NATIVE}); ev.record("TC-07", f"[{tag}] sales viewer create card in assigned collection", "open(200)" if expect_open else "denied", c, ok(c))
    if c == 200: admin.call("DELETE", f"/api/card/{d['id']}")
    c, d, _ = vs.call("GET", "/api/search?q=report"); titles = [r["name"] for r in (d.get("data") if isinstance(d, dict) else []) ]
    leak = [t for t in titles if "fixture_zero" in t]
    ev.record("TC-07", f"[{tag}] search results leak unassigned titles/metadata", "leak present" if expect_open else "no unassigned titles", f"{len(titles)} results, unassigned visible: {leak[:2]}", bool(leak) if expect_open else not leak)
    c, d, _ = vs.call("GET", "/api/collection"); names = [x["name"] for x in d] if c == 200 else []
    ev.record("TC-07", f"[{tag}] collection list shows unassigned collection", "visible" if expect_open else "hidden", names, ("Finance Reports" in names) if expect_open else ("Finance Reports" not in names))
    for path in ["/api/user", "/api/permissions/group", "/api/setting", "/api/database"]:
        c, d, _ = vs.call("GET", path)
        body = json.dumps(d, default=str)[:60]
        if path == "/api/database":
            names = [x["name"] for x in (d["data"] if isinstance(d, dict) else d)] if c == 200 else []
            ev.record("TC-07", f"[{tag}] viewer GET {path} (lists data sources)", "visible" if expect_open else "no sources listed", f"{c} {names}", bool(names) if expect_open else not names)
        else:
            ev.record("TC-07", f"[{tag}] viewer GET admin endpoint {path}", "n/a-baseline" if expect_open else "denied(403)", f"{c} {body}", True if expect_open else c in (401, 403))
mode = sys.argv[1]
if mode == "baseline":
    probes("baseline", True)
elif mode == "harden":
    c, g, _ = admin.call("GET", "/api/permissions/group"); gid = {x["name"]: x["id"] for x in g}
    for n in ["Sales Viewers", "Finance Viewers"]:
        if n not in gid: gid[n] = admin.call("POST", "/api/permissions/group", {"name": n})[1]["id"]
    for uid, gn in [(uS, "Sales Viewers"), (uF, "Finance Viewers")]:
        c, d, _ = admin.call("POST", "/api/permissions/membership", {"group_id": gid[gn], "user_id": uid}); print("membership", gn, c)
    # data permissions: viewers may SEE saved results but can create NO queries and download nothing
    c, pg, _ = admin.call("GET", "/api/permissions/graph")
    upd = {"revision": pg["revision"], "groups": {str(g_): {str(st["db_id"]): {"view-data": "unrestricted", "create-queries": "no", "download": {"schemas": "none"}}} for g_ in [1, gid["Sales Viewers"], gid["Finance Viewers"]]}}
    c, d, _ = admin.call("PUT", "/api/permissions/graph", upd); print("PUT data graph:", c, str(d)[:200])
    # collection permissions: All Users none everywhere; each viewer group READ on its own collection only
    c, cg, _ = admin.call("GET", "/api/collection/graph"); C = st["collections"]
    groups = {str(1): {k: "none" for k in cg["groups"]["1"]}, str(gid["Sales Viewers"]): {str(C["Sales Reports"]): "read"}, str(gid["Finance Viewers"]): {str(C["Finance Reports"]): "read"}}
    c, d, _ = admin.call("PUT", "/api/collection/graph", {"revision": cg["revision"], "groups": groups}); print("PUT collection graph:", c, str(d)[:200])
    st["groups"] = gid; json.dump(st, open(ROOT / "evidence/mb_state.json", "w"), indent=1)
elif mode == "hardened":
    probes("hardened", False)
elif mode == "revocation":
    # TC-11: viewer has a live session; admin deactivates; the SAME token must stop working immediately
    c, d, _ = vs.call("GET", f"/api/dashboard/{SALES['dashboard']}"); ev.record("TC-11", "viewer works before revocation", 200, c, c == 200)
    c, d, _ = admin.call("DELETE", f"/api/user/{uS}"); ev.record("TC-11", "admin deactivates user", "200", c, c == 200)
    c, d, _ = vs.call("GET", f"/api/dashboard/{SALES['dashboard']}"); ev.record("TC-11", "revoked user's existing session token on assigned dashboard", "401/403", f"{c}", c in (401, 403))
    c, d, _ = vs.call("POST", f"/api/dashboard/{SALES['dashboard']}/dashcard/{SALES['dashcards']['Revenue']}/card/{SALES['cards']['Revenue']}/query", {"parameters": []}); ev.record("TC-11", "revoked token: data query", "401/403", f"{c}", c in (401, 403))
    t = MB().login("viewer.sales@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"]); ev.record("TC-11", "revoked user cannot log in again", "no session", t, t is None)
    admin.call("PUT", f"/api/user/{uS}/reactivate")
    # group-removal revocation (assignment revoked but account active)
    vs.token = vs.login("viewer.sales@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"]); gid = st["groups"]
    c, mem, _ = admin.call("GET", "/api/permissions/membership"); mid = [m["membership_id"] for m in mem.get(str(uS), []) if m["group_id"] == gid["Sales Viewers"]] if isinstance(mem, dict) else []
    c, d, _ = vs.call("GET", f"/api/dashboard/{SALES['dashboard']}"); ev.record("TC-11", "reactivated viewer regains assigned access", 200, c, c == 200)
    if mid:
        admin.call("DELETE", f"/api/permissions/membership/{mid[0]}")
        c, d, _ = vs.call("GET", f"/api/dashboard/{SALES['dashboard']}"); ev.record("TC-11", "assignment revoked (group removed) -> same live session denied", "403", c, c in (401, 403))
        admin.call("POST", "/api/permissions/membership", {"group_id": gid["Sales Viewers"], "user_id": uS})
ev.save() if mode != "harden" else None
if mode != "harden": (EVID / f"metabase_security_{mode}.json").write_text((EVID / "metabase_security.json").read_text())
