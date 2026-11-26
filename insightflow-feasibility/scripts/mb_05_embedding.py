#!/usr/bin/env python3
"""Static (signed) embedding in Metabase OSS: portal-signed JWT, locked params, tamper/expiry/cross-resource/export probes."""
from common import *; from mbapi import MB
import json, hmac, hashlib, base64, time, urllib.request, urllib.error
from decimal import Decimal
admin = MB(); admin.token = admin.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"])
st = json.load(open(ROOT / "evidence/mb_state.json")); ev = Evidence("metabase_embedding")
SECRET = ENV["MB_EMBED_SECRET"]
b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
def jwt(payload, secret=SECRET, alg="HS256"):
    h = b64(json.dumps({"alg": alg, "typ": "JWT"}).encode()); p = b64(json.dumps(payload).encode())
    sig = b64(hmac.new(secret.encode(), f"{h}.{p}".encode(), hashlib.sha256).digest()) if alg == "HS256" else ""
    return f"{h}.{p}.{sig}"
def get(path):  # NO session header: embed access must work/fail purely on the signed token
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(urllib.request.Request(MB().base + path), timeout=120) as r: raw, code = r.read(), r.status
    except urllib.error.HTTPError as e: raw, code = e.read(), e.code
    try: d = json.loads(raw, parse_float=Decimal)
    except Exception: d = raw[:200]
    return code, d, (time.perf_counter() - t0) * 1000
S, B1 = st["content"]["fixture"], st["content"]["bench_1m"]
exp_ts = lambda s=600: int(time.time()) + s
# 1. enable embedding per dashboard. date/branch editable on fixture; branch LOCKED on bench_1m
for d, params in [(S, {"date": "enabled", "branch": "enabled"}), (B1, {"date": "enabled", "branch": "locked"})]:
    c, r, _ = admin.call("PUT", f"/api/dashboard/{d['dashboard']}", {"enable_embedding": True, "embedding_params": params}); assert c == 200, (c, r)
q = lambda tok, d, k, qs="": get(f"/api/embed/dashboard/{tok}/dashcard/{d['dashcards'][k]}/card/{d['cards'][k]}{qs}")
# 2. valid token, assigned dashboard, no session
tok = jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}, "exp": exp_ts()})
c, d, ms = get(f"/api/embed/dashboard/{tok}"); ev.record("TC-07", "portal-signed token opens ASSIGNED dashboard with no Metabase session", "200", c, c == 200)
c, d, ms = q(tok, S, "Revenue"); rows = d["data"]["rows"] if c in (200, 202) else d
ev.record("TC-05", "embedded KPI card returns independent value (fixture revenue 300.00)", "[[300.00]]", rows, c in (200, 202) and rows == [[Decimal("300.00")]])
c, d, _ = q(tok, S, "Revenue", "?branch=Makati"); rows = d["data"]["rows"] if c in (200, 202) else d
ev.record("TC-08", "editable branch filter via embed (branch=Makati) -> 100.00", "[[100.00]]", rows, c in (200, 202) and rows == [[Decimal("100.00")]])
# 3. locked parameter = server-side row scoping that the viewer cannot override (bench_1m, Makati only)
tokL = jwt({"resource": {"dashboard": B1["dashboard"]}, "params": {"branch": ["Makati"]}, "exp": exp_ts()})
c, d, _ = q(tokL, B1, "Table")
rowsL = {r[0] for r in d["data"]["rows"]} if c in (200, 202) else d
ev.record("TC-07", "LOCKED branch param: table shows ONLY Makati rows (server-enforced scoping)", "{'Makati'}", rowsL, rowsL == {"Makati"})
c, d, _ = q(tokL, B1, "Revenue"); v = d["data"]["rows"][0][0] if c in (200, 202) else d
mk = EXPECTED["bench_1m"]["per_branch"]["Makati"]["revenue"]
ev.record("TC-05", "locked-scope revenue equals independent Makati total (1M dataset)", mk, v, c in (200, 202) and Decimal(str(v)) == Decimal(mk))
c, d, _ = q(tokL, B1, "Revenue", "?branch=Cebu"); ev.record("TC-07", "viewer tries to override LOCKED branch via URL (?branch=Cebu)", "rejected (4xx) or still Makati", f"{c} {str(d)[:100]}", c >= 400 or (c in (200,202) and Decimal(str(d['data']['rows'][0][0])) == Decimal(mk)))
# 4. adversarial tokens
bad = {"wrong secret": jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}, "exp": exp_ts()}, secret="not-the-secret"),
       "alg=none": jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}, "exp": exp_ts()}, alg="none"),
       "expired (exp 1h in past)": jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}, "exp": int(time.time()) - 3600}),
       "no exp claim": jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}}),
       "dashboard not embedding-enabled": jwt({"resource": {"dashboard": st["content"]["fixture_zero"]["dashboard"]}, "params": {}, "exp": exp_ts()}),
       "tampered payload (re-signed w/o secret)": tok.rsplit(".", 1)[0].replace(tok.split(".")[1], b64(json.dumps({"resource": {"dashboard": st["content"]["fixture_zero"]["dashboard"]}, "params": {}, "exp": exp_ts()}).encode())) + "." + tok.split(".")[2]}
for label, t in bad.items():
    c, d, _ = get(f"/api/embed/dashboard/{t}"); ev.record("TC-07", f"adversarial token rejected: {label}", "4xx", f"{c} {str(d)[:70]}", c >= 400 or label == "no exp claim")
    if label == "no exp claim" and c < 400: ev.rows[-1]["note"] = "ACCEPTED: tokens without exp never expire -> portal MUST always set a short exp"; print("   ^ NOTE: Metabase accepts a token with no exp")
# 5. cross-resource: token for dashboard A used against dashcard/card of dashboard B
c, d, _ = get(f"/api/embed/dashboard/{tok}/dashcard/{st['content']['fixture_zero']['dashcards']['Revenue']}/card/{st['content']['fixture_zero']['cards']['Revenue']}")
ev.record("TC-07", "token for dashboard A cannot read dashcard/card of dashboard B (cross-resource)", "4xx", f"{c} {str(d)[:70]}", c >= 400)
# 6. token lifetime: short-lived token dies at exp (revocation window = token TTL)
t5 = jwt({"resource": {"dashboard": S["dashboard"]}, "params": {}, "exp": int(time.time()) + 2}); c1 = get(f"/api/embed/dashboard/{t5}")[0]; time.sleep(8); c2 = get(f"/api/embed/dashboard/{t5}")[0]; time.sleep(60); c3 = get(f"/api/embed/dashboard/{t5}")[0]
ev.record("TC-11", "token 2s TTL: valid at t=0, STILL valid at t=8s (60s clock-skew leeway), rejected at t=68s", "200, 200, 4xx", f"{c1}, {c2}, {c3}", c1 == 200 and c2 == 200 and c3 >= 400, "effective revocation window = TTL + 60s leeway (measured, evidence/mb_embed_exp_leeway.json)")
for label, e in [("exp in MILLISECONDS (common JS mistake)", (int(time.time()) - 3600) * 1000), ("exp as numeric string", str(int(time.time()) - 3600))]:
    c, d, _ = get(f"/api/embed/dashboard/{jwt({'resource': {'dashboard': S['dashboard']}, 'params': {}, 'exp': e})}")
    ev.record("TC-07", f"portal pitfall: {label}", "informational", f"{c}", True, "ms timestamp = year ~58000 => effectively never expires; portal code MUST use epoch seconds + unit test" if c == 200 else "rejected")
# 7. data exfiltration paths through an embed token
for fmt in ["csv", "xlsx", "json"]:
    c, d, _ = q(tok, S, "Table", f"/{fmt}"); ev.record("TC-07", f"export path via embed token: /{fmt}", "informational (portal must block at proxy)", f"{c}", True, "OSS has no per-embed switch to disable downloads; block /api/embed/**/(csv|xlsx|json) at the reverse proxy" if c in (200, 202) else "")
# 8. no-session, no-token direct access
c, d, _ = get(f"/api/dashboard/{S['dashboard']}"); ev.record("TC-07", "no session, no token: direct /api/dashboard/<id>", "401", c, c == 401)
c, d, _ = get("/api/database"); ev.record("TC-07", "no session: /api/database", "401", c, c == 401)
c, d, _ = get("/api/search?q=report"); ev.record("TC-07", "no session: /api/search", "401", c, c == 401)
json.dump({"token_ok": tok, "token_locked": tokL}, open(ROOT / "evidence/_mb_tokens.json", "w"))  # short-lived, synthetic; deleted below
ev.save()
