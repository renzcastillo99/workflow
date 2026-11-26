"""Server-side Superset client using the LEAST-PRIVILEGE service account (can only mint guest tokens + invalidate cache). Browsers never see its credentials."""
import httpx, threading, re
from config import SUPERSET_URL, SVC_USER, SVC_PASSWORD
class SupersetError(Exception): pass
_lock = threading.Lock(); _c = httpx.Client(base_url=SUPERSET_URL, timeout=30); _h = {}
def _login():
    r = _c.post("/api/v1/security/login", json={"username": SVC_USER, "password": SVC_PASSWORD, "provider": "db", "refresh": True})
    if r.status_code != 200: raise SupersetError(f"service login failed ({r.status_code})")
    _h.clear(); _h["Authorization"] = "Bearer " + r.json()["access_token"]
    t = _c.get("/api/v1/security/csrf_token/", headers=_h)
    if t.status_code != 200: raise SupersetError("csrf token unavailable")
    _h["X-CSRFToken"] = t.json()["result"]; _h["Referer"] = SUPERSET_URL
def _post(path, body):
    with _lock:
        if not _h: _login()
        r = _c.post(path, json=body, headers=_h)
        if r.status_code in (401, 400) and ("expired" in r.text.lower() or "csrf" in r.text.lower() or r.status_code == 401):
            _login(); r = _c.post(path, json=body, headers=_h)
        return r
def rls_rules(dataset_id, branch_scope):
    """Row-level clause is built ONLY from the portal's assignment table and strictly validated (never from request input)."""
    if not branch_scope: return []
    if not re.fullmatch(r"[A-Za-z][A-Za-z .'-]{0,40}", branch_scope): raise SupersetError("invalid scope")
    return [{"dataset": dataset_id, "clause": "branch = '" + branch_scope.replace("'", "''") + "'"}]
def guest_token(user_key, dashboard_uuid, dataset_id, branch_scope):
    body = {"user": {"username": f"portal:{user_key}", "first_name": "Portal", "last_name": "User"}, "resources": [{"type": "dashboard", "id": dashboard_uuid}], "rls": rls_rules(dataset_id, branch_scope)}
    r = _post("/api/v1/security/guest_token/", body)
    if r.status_code != 200: raise SupersetError(f"guest token refused ({r.status_code})")
    return r.json()["token"]
def invalidate_cache(dataset_id):
    r = _post("/api/v1/cachekey/invalidate", {"datasource_uids": [f"{dataset_id}__table"]}); return r.status_code in (200, 201)
