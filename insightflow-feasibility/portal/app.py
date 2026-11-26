"""InsightFlow BI - MINI portal (Phase 2). Authentication: any OIDC IdP (Keycloak here; Microsoft Entra by changing OIDC_* settings).
Authorization: this portal's own database (default-deny). Data: Superset embedded via short-lived, row-scoped guest tokens minted server-side."""
import datetime as dt, secrets, tempfile, os, json
from urllib.parse import urlencode
from fastapi import FastAPI, Request, Form, UploadFile, File, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware
from starlette.exceptions import HTTPException as StarletteHTTPException
from authlib.integrations.starlette_client import OAuth
import config as C, db, superset, ingest
from pathlib import Path
BASE = Path(__file__).resolve().parent
db.init()
app = FastAPI(title="InsightFlow BI (mini)", docs_url=None, redoc_url=None, openapi_url=None)
app.add_middleware(SessionMiddleware, secret_key=C.OIDC_SESSION_SECRET, session_cookie="if_oidc", max_age=600, same_site="lax", https_only=C.COOKIE_SECURE)   # transient OIDC state only
app.mount("/static", StaticFiles(directory=BASE / "static"), name="static")
T = Jinja2Templates(directory=str(BASE / "templates"))
oauth = OAuth(); oauth.register("idp", client_id=C.OIDC_CLIENT_ID, client_secret=C.OIDC_CLIENT_SECRET, server_metadata_url=C.OIDC_ISSUER.rstrip("/") + "/.well-known/openid-configuration",
                                client_kwargs={"scope": "openid profile email", "code_challenge_method": "S256"})
def age(ts):
    if not ts: return "never"
    m = int((dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ts)).total_seconds() // 60)
    return "just now" if m < 1 else f"{m} min ago" if m < 120 else f"{m // 60} h ago" if m < 2880 else f"{m // 1440} days ago"
T.env.filters["age"] = age
T.env.filters["ts"] = lambda s: (s or "")[:19].replace("T", " ") + (" UTC" if s else "")
def ip(r): return r.client.host if r.client else ""
# ---------- security headers ----------
@app.middleware("http")
async def headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = f"default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; frame-src {C.SUPERSET_URL}; connect-src 'self'; base-uri 'none'; form-action 'self' {C.OIDC_ISSUER.split('/realms')[0] if '/realms' in C.OIDC_ISSUER else 'https://login.microsoftonline.com'}; frame-ancestors 'none'"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"   # Superset validates the embedding origin from Referer; only the ORIGIN is sent cross-site
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    if not request.url.path.startswith("/static"): resp.headers["Cache-Control"] = "no-store"
    if C.COOKIE_SECURE: resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return resp
# ---------- sessions & auth ----------
def current(request):
    sid = request.cookies.get("if_sid")
    if not sid: return None
    s = db.one("SELECT s.sid, s.csrf, s.created_at, s.last_seen, u.id, u.email, u.name, u.role, u.active FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.sid=?", sid)
    if not s or not s["active"]: return None
    n = dt.datetime.now(dt.timezone.utc)
    if (n - dt.datetime.fromisoformat(s["last_seen"])).total_seconds() > C.SESSION_IDLE_MIN * 60 or (n - dt.datetime.fromisoformat(s["created_at"])).total_seconds() > C.SESSION_ABS_MIN * 60:
        db.run("DELETE FROM sessions WHERE sid=?", sid); db.audit(s["email"], "session.expired", "", "ok", ip(request)); return None
    if (n - dt.datetime.fromisoformat(s["last_seen"])).total_seconds() > 20: db.run("UPDATE sessions SET last_seen=? WHERE sid=?", db.now(), sid)
    return s
def need_user(request):
    u = current(request)
    if not u: raise HTTPException(401)
    return u
def need_admin(request):
    u = need_user(request)
    if u["role"] != "admin": db.audit(u["email"], "admin.denied", request.url.path, "denied", ip(request)); raise HTTPException(403)
    return u
def csrf_ok(u, token):
    if not token or not secrets.compare_digest(token, u["csrf"]): db.audit(u["email"], "csrf.rejected", "", "denied"); raise HTTPException(403, "Invalid form token")
def flash(resp, msg, kind="ok"): resp.set_cookie("if_flash", json.dumps([kind, msg])[:300].encode().hex(), max_age=30, httponly=True, samesite="lax"); return resp
def render(request, name, u=None, status=200, **kw):
    f = request.cookies.get("if_flash"); fl = None
    if f:
        try: fl = json.loads(bytes.fromhex(f).decode())
        except Exception: fl = None
    resp = T.TemplateResponse(request, name, {"user": u, "csrf": u["csrf"] if u else "", "flash": fl, "path": request.url.path, "superset_url": C.SUPERSET_URL, **kw}, status_code=status)
    if f: resp.delete_cookie("if_flash")
    return resp
@app.exception_handler(StarletteHTTPException)
async def http_err(request: Request, exc: StarletteHTTPException):
    if exc.status_code == 401:
        return JSONResponse({"error": "unauthenticated"}, 401) if request.url.path.startswith("/api") else RedirectResponse("/signin?reason=expired", 303)
    if request.url.path.startswith("/api"): return JSONResponse({"error": "denied" if exc.status_code == 403 else "error"}, exc.status_code)
    u = current(request); title = {403: "Permission denied", 404: "Page not found"}.get(exc.status_code, "Something went wrong")
    msg = {403: "You don't have access to this page or report. If you think you should, ask your administrator.", 404: "That page doesn't exist."}.get(exc.status_code, "Please try again.")
    return render(request, "error.html", u, exc.status_code, title=title, message=msg)
# ---------- sign-in (OIDC) ----------
@app.get("/signin", response_class=HTMLResponse)
def signin(request: Request, reason: str = ""):
    msgs = {"expired": "Your session ended. Please sign in again.", "signedout": "You have been signed out.", "failed": "Sign-in could not be completed. Please try again.", "denied": "Your account is not authorised for InsightFlow BI. Ask your administrator."}
    return render(request, "signin.html", None, message=msgs.get(reason, ""), kind=reason)
@app.get("/login")
async def login(request: Request): return await oauth.idp.authorize_redirect(request, C.PORTAL_URL + "/auth/callback")
@app.get("/auth/callback")
async def callback(request: Request):
    try: token = await oauth.idp.authorize_access_token(request)
    except Exception as e: db.audit("", "login.failed", "oidc", "denied", ip(request), type(e).__name__); return RedirectResponse("/signin?reason=failed", 303)
    claims = dict(token.get("userinfo") or {}); oid = claims.get("oid") or claims.get("sub"); email = (claims.get("email") or claims.get("preferred_username") or "").lower()
    def deny(why):
        db.audit(email or oid or "", "login.denied", why, "denied", ip(request)); request.session.clear(); return RedirectResponse("/signin?reason=denied", 303)
    if not oid or not email: return deny("missing identity claims")
    if C.OIDC_REQUIRED_TID and claims.get("tid") != C.OIDC_REQUIRED_TID: return deny("wrong tenant")
    if C.REQUIRE_MFA_CLAIM and not ({"mfa", "otp"} & set(claims.get("amr") or [])): return deny("no MFA in token")
    u = db.one("SELECT * FROM users WHERE oid=?", oid)
    if not u:
        u = db.one("SELECT * FROM users WHERE email=?", email)
        if not u: return deny("not provisioned")
        if u["oid"] and u["oid"] != oid: return deny("identity mismatch")
        db.run("UPDATE users SET oid=? WHERE id=?", oid, u["id"])                                   # bind identity at first login
    if not u["active"]: return deny("deactivated")
    sid = db.new_sid(); db.run("INSERT INTO sessions(sid,user_id,csrf,created_at,last_seen,id_token) VALUES(?,?,?,?,?,?)", sid, u["id"], secrets.token_urlsafe(24), db.now(), db.now(), token.get("id_token"))
    db.run("UPDATE users SET last_login=? WHERE id=?", db.now(), u["id"]); db.audit(u["email"], "login.success", "", "ok", ip(request), f"amr={claims.get('amr')}"); request.session.clear()
    r = RedirectResponse("/", 303); r.set_cookie("if_sid", sid, httponly=True, samesite="lax", secure=C.COOKIE_SECURE, max_age=C.SESSION_ABS_MIN * 60, path="/"); return r
@app.post("/logout")
async def logout(request: Request, csrf_token: str = Form("")):
    u = need_user(request); csrf_ok(u, csrf_token)
    s = db.one("SELECT id_token FROM sessions WHERE sid=?", u["sid"]); db.run("DELETE FROM sessions WHERE sid=?", u["sid"]); db.audit(u["email"], "logout", "", "ok", ip(request))
    try:
        md = await oauth.idp.load_server_metadata(); q = {"post_logout_redirect_uri": C.PORTAL_URL + "/signin?reason=signedout", "client_id": C.OIDC_CLIENT_ID}
        if s and s["id_token"]: q["id_token_hint"] = s["id_token"]
        target = md["end_session_endpoint"] + "?" + urlencode(q)
    except Exception: target = "/signin?reason=signedout"
    r = RedirectResponse(target, 303); r.delete_cookie("if_sid"); return r
# ---------- reports ----------
def freshness():
    ok = db.one("SELECT * FROM refresh_jobs WHERE status='success' ORDER BY id DESC LIMIT 1")
    bad = db.one("SELECT * FROM refresh_jobs WHERE status IN ('failed','rejected') AND id>? ORDER BY id DESC LIMIT 1", ok["id"] if ok else 0)
    stale = bool(ok) and (dt.datetime.now(dt.timezone.utc) - dt.datetime.fromisoformat(ok["finished_at"] or ok["started_at"])).total_seconds() > C.STALE_AFTER_MINUTES * 60
    return {"last_ok": ok, "last_bad": bad, "stale": stale or not ok}
def my_reports(u):
    if u["role"] == "admin": rows = db.q("SELECT r.*, NULL AS branch_scope FROM reports r ORDER BY title")
    else: rows = db.q("SELECT r.*, a.branch_scope FROM reports r JOIN assignments a ON a.report_id=r.id WHERE a.user_id=? ORDER BY title", u["id"])
    return rows
def access(u, rid):
    return next((r for r in my_reports(u) if r["id"] == rid), None)
@app.get("/", response_class=HTMLResponse)
def overview(request: Request):
    u = current(request)
    if not u: return RedirectResponse("/signin", 303)
    ops = None
    if u["role"] == "admin":
        ops = {"users": db.one("SELECT count(*) n FROM users WHERE active=1")["n"], "no_assign": db.one("SELECT count(*) n FROM users u WHERE role='viewer' AND active=1 AND NOT EXISTS(SELECT 1 FROM assignments a WHERE a.user_id=u.id)")["n"],
               "bad_jobs": db.one("SELECT count(*) n FROM refresh_jobs WHERE status IN('failed','rejected') AND started_at > datetime('now','-7 day')")["n"], "denied": db.one("SELECT count(*) n FROM events WHERE outcome='denied' AND ts > datetime('now','-1 day')")["n"]}
    return render(request, "overview.html", u, reports=my_reports(u), fresh=freshness(), ops=ops)
@app.get("/reports", response_class=HTMLResponse)
def library(request: Request):
    u = need_user(request); return render(request, "reports.html", u, reports=my_reports(u), fresh=freshness())
@app.get("/reports/{rid}", response_class=HTMLResponse)
def report(request: Request, rid: str):
    u = need_user(request); r = access(u, rid)
    if not r: db.audit(u["email"], "report.denied", rid, "denied", ip(request)); raise HTTPException(403)       # same answer whether or not the report exists
    return render(request, "report.html", u, r=r, fresh=freshness() if r["live"] else None)
@app.get("/api/reports/{rid}/guest-token")
def guest(request: Request, rid: str):
    u = need_user(request)
    if request.headers.get("sec-fetch-site", "same-origin") not in ("same-origin", "none"): db.audit(u["email"], "token.denied", rid, "denied", ip(request), "cross-site"); raise HTTPException(403)
    r = access(u, rid)
    if not r: db.audit(u["email"], "token.denied", rid, "denied", ip(request)); raise HTTPException(403)
    try: tok = superset.guest_token(u["id"], r["dashboard_uuid"], r["dataset_id"], r["branch_scope"])
    except Exception as e: db.audit(u["email"], "token.error", rid, "error", ip(request), str(e)); return JSONResponse({"error": "The report service is unavailable. Try again shortly."}, 502)
    db.audit(u["email"], "report.view", rid, "ok", ip(request), f"scope={r['branch_scope'] or 'all'}"); return JSONResponse({"token": tok}, headers={"Cache-Control": "no-store"})
# ---------- admin: users ----------
@app.get("/admin/users", response_class=HTMLResponse)
def users(request: Request):
    u = need_admin(request); us = db.q("SELECT * FROM users ORDER BY role, name")
    for x in us: x["assign"] = db.q("SELECT a.report_id, a.branch_scope, r.title FROM assignments a JOIN reports r ON r.id=a.report_id WHERE a.user_id=? ORDER BY r.title", x["id"])
    return render(request, "users.html", u, users=us, reports=db.q("SELECT id,title FROM reports ORDER BY title"), branches=C.KNOWN_BRANCHES)
def back(msg, kind="ok", to="/admin/users"): return flash(RedirectResponse(to, 303), msg, kind)
@app.post("/admin/users/add")
def user_add(request: Request, email: str = Form(...), name: str = Form(...), role: str = Form("viewer"), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); email = email.strip().lower(); name = name.strip()[:80]
    import re
    if not re.fullmatch(r"[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{2,20}", email) or not name or role not in ("admin", "viewer"): return back("Enter a valid e-mail, name and role.", "error")
    if db.one("SELECT 1 FROM users WHERE email=?", email): return back("That e-mail is already provisioned.", "error")
    db.run("INSERT INTO users(email,name,role,active,created_at) VALUES(?,?,?,1,?)", email, name, role, db.now()); db.audit(u["email"], "user.add", email, "ok", ip(request), f"role={role}")
    return back(f"{email} can now sign in. They see nothing until you assign a report.")
@app.post("/admin/users/{uid}/active")
def user_active(request: Request, uid: int, active: int = Form(...), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); t = db.one("SELECT * FROM users WHERE id=?", uid)
    if not t: raise HTTPException(404)
    if t["id"] == u["id"]: return back("You can't deactivate your own account.", "error")
    if not active and t["role"] == "admin" and db.one("SELECT count(*) n FROM users WHERE role='admin' AND active=1")["n"] <= 1: return back("At least one active administrator is required.", "error")
    db.run("UPDATE users SET active=? WHERE id=?", 1 if active else 0, uid)
    if not active: db.run("DELETE FROM sessions WHERE user_id=?", uid)                                # revoke: live sessions end NOW
    db.audit(u["email"], "user.activate" if active else "user.deactivate", t["email"], "ok", ip(request))
    return back(f"{t['email']} {'re-activated' if active else 'deactivated: portal sessions ended immediately. A report already open can keep its data for up to 5 minutes (guest-token lifetime).'}")
@app.post("/admin/users/{uid}/role")
def user_role(request: Request, uid: int, role: str = Form(...), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); t = db.one("SELECT * FROM users WHERE id=?", uid)
    if not t or role not in ("admin", "viewer"): raise HTTPException(404)
    if t["id"] == u["id"]: return back("You can't change your own role.", "error")
    db.run("UPDATE users SET role=? WHERE id=?", role, uid); db.audit(u["email"], "user.role", t["email"], "ok", ip(request), f"role={role}"); return back(f"{t['email']} is now {role}.")
@app.post("/admin/assign")
def assign(request: Request, user_id: int = Form(...), report_id: str = Form(...), scope: str = Form(""), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); t = db.one("SELECT * FROM users WHERE id=?", user_id); r = db.one("SELECT * FROM reports WHERE id=?", report_id)
    if not t or not r or (scope and scope not in C.KNOWN_BRANCHES): return back("Invalid selection.", "error")
    db.run("INSERT OR REPLACE INTO assignments(user_id,report_id,branch_scope,created_at) VALUES(?,?,?,?)", user_id, report_id, scope or None, db.now())
    db.audit(u["email"], "assignment.add", f"{t['email']} -> {report_id}", "ok", ip(request), f"scope={scope or 'all'}"); return back(f"{t['name']} can now open “{r['title']}” ({scope or 'all branches'}).")
@app.post("/admin/unassign")
def unassign(request: Request, user_id: int = Form(...), report_id: str = Form(...), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); t = db.one("SELECT * FROM users WHERE id=?", user_id)
    if not t: raise HTTPException(404)
    db.run("DELETE FROM assignments WHERE user_id=? AND report_id=?", user_id, report_id); db.audit(u["email"], "assignment.revoke", f"{t['email']} -> {report_id}", "ok", ip(request))
    return back(f"Access revoked. New report opens are denied now; one already open can keep its data for up to 5 minutes.")
# ---------- admin: data ----------
@app.get("/admin/data", response_class=HTMLResponse)
def data_page(request: Request):
    u = need_admin(request)
    try: live = ingest.live_summary()
    except Exception: live = None
    return render(request, "data.html", u, live=live, fresh=freshness(), last=db.one("SELECT * FROM refresh_jobs ORDER BY id DESC LIMIT 1"), required=ingest.REQUIRED)
@app.post("/admin/data/upload")
def data_upload(request: Request, file: UploadFile = File(...), csrf_token: str = Form("")):
    u = need_admin(request); csrf_ok(u, csrf_token); name = os.path.basename(file.filename or "upload")[:100]
    jid = db.run("INSERT INTO refresh_jobs(started_at,source_name,source_type,status,triggered_by) VALUES(?,?,?,?,?)", db.now(), name, name.rsplit(".", 1)[-1].lower(), "running", u["email"])
    def finish(status, msg, rows_read=0, pub=0, rej=None):
        db.run("UPDATE refresh_jobs SET finished_at=?,status=?,message=?,rows_read=?,rows_published=?,rejected_json=? WHERE id=?", db.now(), status, msg[:500], rows_read, pub, json.dumps(rej or []), jid)
        db.audit(u["email"], "refresh." + status, name, "ok" if status == "success" else "denied" if status == "rejected" else "error", ip(request), msg[:200])
    data = b""; 
    while chunk := file.file.read(1 << 20):
        data += chunk
        if len(data) > C.MAX_UPLOAD_BYTES: finish("rejected", f"File larger than {C.MAX_UPLOAD_BYTES // 1048576} MB - rejected, live data unchanged"); return back("File too large. Live data unchanged.", "error", "/admin/data")
    tmp = None
    try:
        with ingest.exclusive():
            tmp, n, rev, cost = ingest.validate(name, data); pub = ingest.publish(tmp, n, rev, cost)
        note = "published"; 
        try: note += "; BI cache refreshed" if superset.invalidate_cache(db.one("SELECT dataset_id FROM reports WHERE live=1")["dataset_id"]) else "; WARNING: BI cache not refreshed (may show old numbers for up to 5 min)"
        except Exception: note += "; WARNING: BI cache not refreshed"
        finish("success", f"{n:,} rows validated, reconciled (count, revenue {rev}, cost {cost}) and {note}", n, pub)
        return back(f"Published {n:,} rows. Reports now show the new data.", "ok", "/admin/data")
    except ingest.Busy as e: finish("rejected", str(e)); return back(str(e), "error", "/admin/data")
    except ingest.IngestError as e: finish("rejected" if e.rejected or "Schema" in str(e) or "valid" in str(e) or "Unsupported" in str(e) or "empty" in str(e) or "UTF" in str(e) or "rows" in str(e) else "failed", str(e), e.rows_read, 0, e.rejected); return back(f"{e} The live data was not changed.", "error", "/admin/data")
    except Exception as e: finish("failed", f"Unexpected error ({type(e).__name__}) - live data unchanged"); return back("Unexpected error. The live data was not changed.", "error", "/admin/data")
    finally:
        if tmp and os.path.exists(tmp): os.unlink(tmp)
@app.get("/admin/refresh", response_class=HTMLResponse)
def refresh_page(request: Request):
    u = need_admin(request); jobs = db.q("SELECT * FROM refresh_jobs ORDER BY id DESC LIMIT 100")
    for j in jobs: j["rejected"] = json.loads(j["rejected_json"] or "[]")
    return render(request, "refresh.html", u, jobs=jobs, fresh=freshness())
@app.get("/admin/audit", response_class=HTMLResponse)
def audit_page(request: Request, outcome: str = "", q: str = ""):
    u = need_admin(request); sql, a = "SELECT * FROM events WHERE 1=1", []
    if outcome in ("ok", "denied", "error"): sql += " AND outcome=?"; a.append(outcome)
    if q: sql += " AND (actor LIKE ? OR action LIKE ? OR target LIKE ?)"; a += [f"%{q[:40]}%"] * 3
    return render(request, "audit.html", u, events=db.q(sql + " ORDER BY id DESC LIMIT 200", *a), outcome=outcome, q=q)
@app.get("/settings", response_class=HTMLResponse)
def settings(request: Request): u = need_user(request); return render(request, "settings.html", u, idle=C.SESSION_IDLE_MIN, absolute=C.SESSION_ABS_MIN)
@app.get("/healthz")
def healthz(): return {"status": "ok"}
