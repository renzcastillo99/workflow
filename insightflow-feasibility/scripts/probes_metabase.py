#!/usr/bin/env python3
"""Probes that were run INLINE during the session and are saved here afterwards (transcribed; NOT re-executed in this saved form).
The evidence JSONs in ../evidence came from the original runs. Usage: python3 probes_metabase.py [capabilities|throttle|session_expiry|leeway]"""
import sys, time, json, hmac, hashlib, base64, urllib.request, urllib.error
from common import *; from mbapi import MB
def capabilities():
    mb = MB(); mb.token = mb.login("admin@feasibility.invalid", ENV["MB_ADMIN_PASSWORD"]); ev = Evidence("metabase_oss_capabilities_rerun")
    for label, method, path, body in [("brand colour", "PUT", "/api/setting/application-colors", {"value": {"brand": "#2563EB"}}), ("custom font", "PUT", "/api/setting/application-font", {"value": "Inter"}),
        ("logo", "PUT", "/api/setting/application-logo-url", {"value": "https://example.invalid/x.png"}), ("MFA required", "PUT", "/api/setting/mfa-enforcement", {"value": "required"}),
        ("sandbox", "POST", "/api/mt/gtap", {}), ("audit app", "GET", "/api/ee/audit-app/user/audit-info", None)]:
        c, d, _ = mb.call(method, path, body); ev.record("CAP", label, "blocked in OSS", f"HTTP {c}", c >= 400, status="LIMITATION")
    ev.save()
def throttle():
    m = MB(); res = [m.call("POST", "/api/session", {"username": "lockout.probe@feasibility.invalid", "password": f"wrong-{i}"}, token=None) for i in range(15)]
    print([c for c, _, _ in res], [d for c, d, _ in res if "Too many" in str(d)][:1])
def session_expiry():  # requires Metabase started with MB_MAX_SESSION_AGE=1
    t = MB().login("viewer.sales@feasibility.invalid", ENV["MB_VIEWER_PASSWORD"]); v = MB(); v.token = t
    print("t=0", v.call("GET", "/api/user/current")[0]); time.sleep(75); print("t=75s", v.call("GET", "/api/user/current")[0])
def leeway():
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
    def jwt(p):
        h = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()); pl = b64(json.dumps(p).encode())
        return f"{h}.{pl}." + b64(hmac.new(ENV["MB_EMBED_SECRET"].encode(), f"{h}.{pl}".encode(), hashlib.sha256).digest())
    st = json.load(open(ROOT / "evidence/mb_state.json")); did = st["content"]["fixture"]["dashboard"]; out = {}
    for off in [10, 30, 50, 58, 62, 70, 90, 120]:
        try: out[off] = urllib.request.urlopen(f"{MB().base}/api/embed/dashboard/{jwt({'resource': {'dashboard': did}, 'params': {}, 'exp': int(time.time()) - off})}").status
        except urllib.error.HTTPError as e: out[off] = e.code
    print(out)
if __name__ == "__main__": globals()[sys.argv[1]]()
