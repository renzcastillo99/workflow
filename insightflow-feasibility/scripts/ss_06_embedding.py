#!/usr/bin/env python3
"""Superset EMBEDDED_SUPERSET guest tokens: portal-issued, per-token RLS, adversarial tokens, export, leeway, framing headers."""
from common import *; from ssapi import SS
import json, hmac, hashlib, base64, time, requests
from decimal import Decimal
admin = SS(); assert admin.login("admin", ENV["SS_ADMIN_PASSWORD"]); st = json.load(open(ROOT / "evidence/ss_state.json")); ev = Evidence("superset_embedding")
D, DS = st["dashboards"], st["datasets"]; b64d = lambda s: base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)); b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
# guest role (what a guest is allowed to do). Reuse minimal viewer permissions WITHOUT datasource grants: guests reach data only through the embedded dashboard.
c, d, _ = admin.call("GET", "/api/v1/security/roles/search/"); roles = {r["name"]: r["id"] for r in d["result"]}
if "InsightFlowGuest" not in roles: roles["InsightFlowGuest"] = admin.call("POST", "/api/v1/security/roles/", json={"name": "InsightFlowGuest"})[1]["id"]
base_ids = admin.call("GET", f"/api/v1/security/roles/{st['roles']['IF_SalesViewer']}/permissions")[1]["result"]
c, perms, _ = admin.call("GET", "/api/v1/security/permissions-resources/?q=(page_size:500)")
pid = {(r["permission"]["name"], r["view_menu"]["name"]): r["id"] for r in perms["result"]}
keep = [pid[(p["permission_name"], p["view_menu_name"])] for p in base_ids if p["permission_name"] != "datasource_access" and (p["permission_name"], p["view_menu_name"]) in pid]
print("guest role perms set:", admin.call("POST", f"/api/v1/security/roles/{roles['InsightFlowGuest']}/permissions", json={"permission_view_menu_ids": keep})[0])
emb = {}
for sch in ["fixture", "bench_1m", "fixture_zero"]:
    if sch == "fixture_zero": continue                       # intentionally NOT embedded
    c, d, _ = admin.call("POST", f"/api/v1/dashboard/{D[sch]}/embedded", json={"allowed_domains": []}); emb[sch] = d["result"]["uuid"]; ev.record("FUNC-18", f"enable embedding on {sch} dashboard", "201/200 + uuid", f"{c} {emb[sch]}", c in (200, 201))
def guest_token(sch, rls=None, user="portal-user-1"):
    body = {"user": {"username": user, "first_name": "Portal", "last_name": "User"}, "resources": [{"type": "dashboard", "id": emb[sch]}], "rls": rls or []}
    c, d, _ = admin.call("POST", "/api/v1/security/guest_token/", json=body); assert c == 200, (c, d); return d["token"]
def claims(tok): return json.loads(b64d(tok.split(".")[1]))
def forge(tok, secret, **over):
    h = json.loads(b64d(tok.split(".")[0])); p = {**claims(tok), **over}; hh = b64(json.dumps(h).encode()); pp = b64(json.dumps(p).encode())
    return f"{hh}.{pp}." + b64(hmac.new(secret.encode(), f"{hh}.{pp}".encode(), hashlib.sha256).digest())
def gq(tok, sch, dash, metrics=("revenue",), filters=None, fmt="json"):
    body = {"datasource": {"id": DS[sch], "type": "table"}, "form_data": {"dashboardId": D[dash]}, "force": False, "result_format": fmt, "result_type": "full",
            "queries": [{"metrics": list(metrics), "columns": [], "filters": filters or [], "row_limit": 10, "extras": {}}]}
    r = requests.post(f"{admin.base}/api/v1/chart/data", json=body, headers={"X-GuestToken": tok}, timeout=120)   # no cookie, no bearer: guest header only
    return r.status_code, r.text
val = lambda t: json.loads(t, parse_float=Decimal)["result"][0]["data"][0]
SECRET = ENV["SS_GUEST_TOKEN_SECRET"]
t1 = guest_token("fixture"); cl = claims(t1)
ev.record("TC-06", "portal-issued guest token claims (ttl = exp-iat)", "ttl 300s, type guest, resources=[embedded dashboard]", {"ttl": cl["exp"] - cl["iat"], "type": cl.get("type"), "res": cl.get("resources"), "aud": cl.get("aud")}, cl["exp"] - cl["iat"] == 300)
c, t = gq(t1, "fixture", "fixture", ("revenue", "gross_profit", "margin", "transactions")); v = val(t) if c == 200 else t[:100]
ev.record("TC-05", "guest token (no session) reads assigned embedded dashboard data: 300/120/0.4/2", "300.00/120.00/0.4/2", v, c == 200 and Decimal(str(v["revenue"])) == 300 and v["transactions"] == 2)
c, t = gq(t1, "fixture", "fixture", filters=[{"col": "branch", "op": "IN", "val": ["Makati"]}]); ev.record("TC-08", "guest filter branch=Makati -> 100.00", "100.00", val(t) if c == 200 else t[:80], c == 200 and Decimal(str(val(t)["revenue"])) == 100)
# per-token RLS: portal scopes a user to Makati; viewer cannot widen it
t2 = guest_token("bench_1m", rls=[{"dataset": DS["bench_1m"], "clause": "branch = 'Makati'"}], user="portal-user-makati")
mk = EXPECTED["bench_1m"]["per_branch"]["Makati"]
c, t = gq(t2, "bench_1m", "bench_1m", ("revenue", "transactions")); v = val(t) if c == 200 else t[:100]
ev.record("TC-07", "per-token RLS (branch='Makati'): totals == independent Makati total", f"{mk['revenue']}/{mk['transaction_count']}", v, c == 200 and Decimal(str(v["revenue"])) == Decimal(mk["revenue"]) and v["transactions"] == mk["transaction_count"])
c, t = gq(t2, "bench_1m", "bench_1m", ("revenue",), [{"col": "branch", "op": "IN", "val": ["Cebu"]}]); v = val(t) if c == 200 else t[:80]
ev.record("TC-07", "RLS bypass attempt: guest adds filter branch=Cebu", "no Cebu data", v, c == 200 and v.get("revenue") is None)
# isolation: token for dashboard A cannot read dataset/dashboard B
c, t = gq(t1, "fixture_zero", "fixture"); ev.record("TC-16", "token for dashboard A: dataset of unassigned dashboard B (dashboardId=A)", "403", f"{c} {t[:70]}", c in (401, 403))
c, t = gq(t1, "fixture_zero", "fixture_zero"); ev.record("TC-07", "token for A claims dashboardId=B (not in token resources)", "403", f"{c} {t[:70]}", c in (401, 403))
c, t = gq(t1, "bench_5m", "fixture"); ev.record("TC-07", "guest ad-hoc query on arbitrary raw dataset (bench_5m)", "403", c, c in (401, 403))
# admin / export / sql lab as guest
H = {"X-GuestToken": t1}
for label, method, path, body in [("admin /security/users/", "GET", "/api/v1/security/users/", None), ("DB list", "GET", "/api/v1/database/", None), ("SQL Lab execute", "POST", "/api/v1/sqllab/execute/", {"database_id": 1, "sql": "select 1"}),
                                  ("dashboard list (other dashboards)", "GET", "/api/v1/dashboard/", None), ("create chart", "POST", "/api/v1/chart/", {"slice_name": "x"})]:
    r = requests.request(method, admin.base + path, headers=H, json=body); ids = None
    leaked = False
    if label.startswith("dashboard list") and r.status_code == 200: leaked = any(x["id"] != D["fixture"] for x in r.json().get("result", []))
    inconclusive = r.status_code == 400 and "CSRF" in r.text
    ev.record("TC-07", f"guest token calls {label}", "denied (or only own dashboard)", f"{r.status_code} {r.text[:60]}", (r.status_code in (400, 401, 403, 404, 422)) or (label.startswith("dashboard list") and not leaked),
              "HTTP 400 CSRF failure masks the authorization decision - see role-permission inspection check" if inconclusive else "", status="INCONCLUSIVE" if inconclusive else None)
gp = admin.call("GET", f"/api/v1/security/roles/{roles['InsightFlowGuest']}/permissions")[1]["result"]; names = sorted({f"{x['permission_name']}@{x['view_menu_name']}" for x in gp})
ACCEPTED = {"can_write@DashboardFilterStateRestApi", "can_write@DashboardPermalinkRestApi"}   # dashboard UI state (filters/permalinks) - accepted, documented
risky = [n for n in names if n not in ACCEPTED and n.startswith(("can_write@", "can_csv@", "can_export", "can_execute", "can_explore_json", "can_samples", "datasource_access", "can_add", "menu_access@SQL", "can_sql_json"))]
ev.record("TC-07", "guest role permission inspection: no write/export/SQL/explore/datasource grants", "no risky permissions", {"total": len(names), "risky": risky, "accepted_ui_state_writes": sorted(ACCEPTED & set(names)), "all": names}, not risky)
c, t = gq(t1, "fixture", "fixture", fmt="csv"); ev.record("TC-07", "guest CSV export (result_format=csv)", "denied by role (export off by default)", f"{c} {t[:60]}", c in (401, 403))
# adversarial tokens
bad = {"wrong secret": forge(t1, "not-the-secret"), "alg=none": b64(b'{"alg":"none","typ":"JWT"}') + "." + t1.split(".")[1] + ".",
       "expired 1h": forge(t1, SECRET, exp=int(time.time()) - 3600),
       "tampered resources (other dashboard uuid)": forge(t1, "wrong", resources=[{"type": "dashboard", "id": emb["bench_1m"]}]),
       "RLS stripped by re-signing w/o secret": forge(t2, "wrong", rls_rules=[])}
for label, tk in bad.items():
    c, t = gq(tk, "fixture", "fixture"); ev.record("TC-07", f"adversarial guest token rejected: {label}", "401/403/422", f"{c} {t[:60]}", c in (401, 403, 422))
ctrl = forge(t1, SECRET); c, t = gq(ctrl, "fixture", "fixture"); ev.record("TC-07", "CONTROL: token re-signed with the real secret is accepted (proves forge() is valid)", "200", c, c == 200, "validates that the rejected tokens above fail for the right reason")
lee = {}
for off in [1, 10, 30, 70, 130]:
    c, t = gq(forge(t1, SECRET, exp=int(time.time()) - off), "fixture", "fixture"); lee[off] = c
ev.record("TC-11", "expiry leeway: seconds past exp -> HTTP", "rejects immediately or small leeway", lee, True, "revocation window = ttl(300s) + leeway", status="INFO")
# framing / headers on embedded page + normal UI
r = requests.get(f"{admin.base}/embedded/{emb['fixture']}"); hdr = {k: v for k, v in r.headers.items() if k.lower() in ("content-security-policy", "x-frame-options", "x-content-type-options", "strict-transport-security", "referrer-policy")}
ev.record("TC-07", "headers on /embedded/<uuid>", "informational", {"code": r.status_code, **hdr}, True, status="INFO")
r = requests.get(f"{admin.base}/login/"); hdr = {k: v for k, v in r.headers.items() if k.lower() in ("content-security-policy", "x-frame-options", "x-content-type-options", "strict-transport-security")}
ev.record("TC-07", "headers on /login/ (clickjacking protection of normal UI)", "informational", hdr, True, status="INFO")
json.dump({"emb": emb, "tok_fixture": "synthetic-short-lived", }, open(ROOT / "evidence/_ss_emb.json", "w")); ev.save()
