#!/usr/bin/env python3
"""Normalises evidence statuses (PASS / FAIL / GAP / LIMITATION / LEAK-REPRODUCED / INFO / INCONCLUSIVE) and writes evidence/SUMMARY.md.
Every relabel is explicit below with a reason; nothing is silently flipped to PASS."""
import json, glob
from pathlib import Path
E = Path(__file__).resolve().parent.parent / "evidence"
def load(n): return json.loads((E / f"{n}.json").read_text())
def save(n, rows): (E / f"{n}.json").write_text(json.dumps(rows, indent=2))
# 1. Metabase baseline: 'PASS' there means 'the default-config leak was reproduced'
for n in ["metabase_security_baseline"]:
    rows = load(n)
    for r in rows:
        if r["expected"] in ("open(200)", "open", "visible", "leak present") and r["status"] == "PASS": r["status"] = "LEAK-REPRODUCED"; r["note"] = "default Metabase config is open: this row documents the vulnerability, it is not a success"
    save(n, rows)
# 2. Metabase OSS capability probes: 'blocked' = confirmed limitation; two predictions were wrong
rows = load("metabase_oss_capabilities")
for r in rows:
    if r["status"] == "PASS": r["status"] = "LIMITATION"; r["note"] = (r["note"] + " | feature confirmed NOT available in OSS").strip(" |")
    if "Google sign-in" in r["check"]: r["status"] = "INFO"; r["note"] = "My prediction (blocked) was WRONG: setting accepted in OSS. enable-sso-google? flag still False; end-to-end Google login NOT VERIFIED (needs a real OAuth client). Setting reverted."
    if "session timeout setting" in r["check"]: r["status"] = "LIMITATION"; r["note"] = "Setting accepted+persisted but NOT enforced server-side (idle 75s with 1-min timeout -> still 200). Use MAX_SESSION_AGE env (verified enforced)."
save("metabase_oss_capabilities", rows)
rows = load("metabase_session_expiry")
for r in rows:
    if "session-timeout' idle" in r["check"]: r["status"] = "LIMITATION"
save("metabase_session_expiry", rows)
rows = load("metabase_embedding")
for r in rows:
    if "export path via embed token" in r["check"]: r["status"] = "LIMITATION"; r["note"] = "OSS has no per-embed switch to disable downloads; block at reverse proxy"
    if "no exp claim" in r["check"]: r["status"] = "LIMITATION"; r["note"] = "Tokens without exp are accepted (never expire). Portal must always set exp. Also: exp in milliseconds accepted as far-future; 60 s leeway measured."
    if "MILLISECONDS" in r["check"]: r["status"] = "LIMITATION"
save("metabase_embedding", rows)
# 3. Superset gaps
rows = load("superset_misc_security")
# replace invalid/mis-specified rows with corrected ones
keep = [r for r in rows if not any(k in r["check"] for k in ["brute-force rate limiting", "admin API masks", "audit covers login"])]
ts = rows[0]["ts"]
keep += [
 {"tc": "TC-06", "check": "brute-force throttling on /login/ (form) and /api/v1/security/login (REST): 20 bad attempts each", "expected": "429/lockout", "observed": "no throttling observed (12-20 bad attempts each: all 302 / all 401). AUTH_RATE_LIMITED='5 per 40 second' is loaded, but the only Redis limiter key present right after the attempts is the GLOBAL one (LIMITER/<ip>/global/50/1/second); no login-specific key => the login limit is not applied to either login path in this build/config (root cause undiagnosed). Separately verified: the global 50 req/s per-IP limit IS active (HTTP 429 under burst)", "status": "GAP", "note": "mitigate at reverse proxy/WAF; keep Superset off the public internet; IdP handles human login", "ts": ts},
 {"tc": "TC-12", "check": "DB credentials never returned by API", "expected": "no password in API/export", "observed": "GET /database/{id} omits sqlalchemy_uri entirely; /connection and export show postgresql+psycopg2://insightflow_ro:XXXXXXXXXX@... (masked); password literal absent from export zip", "status": "PASS", "note": "my first check expected the masked field in GET /database/{id}; the field is simply not returned", "ts": ts},
 {"tc": "TC-12", "check": "Action log covers login/logout events", "expected": "login + access events", "observed": "log records per-API-call actor, dashboard_id, slice_id, duration, payload (e.g. DashboardRestApi.get, ChartDataRestApi.data, RLSRestApi.post, DashboardRestApi.put); NO login/logout events; denied attempts not distinguishable", "status": "GAP", "note": "portal must keep its own login/audit trail", "ts": ts}]
save("superset_misc_security", keep)
# 4. at_rest_and_audit corrections
rows = load("at_rest_and_audit"); fixed = []
for r in rows:
    if "Metabase user passwords hashed" in r["check"]:
        r.update(observed="core_user.password is empty in v0.65; credentials live in auth_identity.credentials (opaque, e.g. 'qTV0Y95D...'), not plaintext", status="PASS", note="my first query read the wrong table")
    if "view_log: rows" in r["check"] or "audit_log: rows" in r["check"]:
        r["status"] = "INFO"; r["note"] = "0 rows: not populated by API/embed access in this test; no audit UI in OSS"
    fixed.append(r)
if not any("attributes embedded-dashboard" in r["check"] for r in fixed): fixed.append({"tc": "TC-12", "check": "Metabase attributes embedded-dashboard query executions to a user", "expected": "executor_id populated", "observed": "query_execution: embedded-dashboard 1737 rows, ALL executor_id NULL (embedded-csv/xlsx/json-download also NULL); only direct logged-in API use is attributed", "status": "LIMITATION", "note": "With static embedding every viewer is anonymous to Metabase; the portal must write the 'who viewed what' audit trail", "ts": fixed[0]["ts"]})
save("at_rest_and_audit", fixed)
# 5. summary
lines = ["# Evidence summary (auto-generated by scripts/finalize_evidence.py)", "", "| Evidence file | PASS | FAIL | Other flagged (GAP/LIMITATION/LEAK-REPRODUCED/INFO/INCONCLUSIVE) | Total |", "|---|---:|---:|---|---:|"]
for f in sorted(E.glob("*.json")):
    if f.name.startswith("_") or f.stem in ("mb_state", "ss_state") or "benchmark" in f.stem or "probe" in f.stem or "leeway" in f.stem or "attribution" in f.stem: continue
    rows = json.loads(f.read_text())
    if not isinstance(rows, list): continue
    from collections import Counter; c = Counter(r["status"] for r in rows)
    other = ", ".join(f"{k}:{v}" for k, v in c.items() if k not in ("PASS", "FAIL"))
    lines.append(f"| {f.name} | {c.get('PASS', 0)} | {c.get('FAIL', 0)} | {other or '-'} | {len(rows)} |")
(E / "SUMMARY.md").write_text("\n".join(lines) + "\n"); print("\n".join(lines))
