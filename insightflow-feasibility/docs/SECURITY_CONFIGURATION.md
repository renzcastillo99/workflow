# InsightFlow BI — Security Configuration Guide (Phase 1)

Applies to the recommended stack: **portal + Apache Superset 6.1 (guest-token embedding) + Postgres**.
Each item is tagged **[VERIFIED]** (I ran a test and have evidence), **[CONFIGURED]** (set in the repo, not independently attacked), or **[TODO]** (design only — not built/tested). Nothing here is a compliance claim.

---

## Part A — Before you test anything at your boss's company

You said you'll test this at your boss's company. That is a *real customer environment*, and the approved spec says: **"No real customer data until authorized"** and lists what the owner must supply before integration. Follow this order.

### A1. Get these in writing first (do not skip)
| Need | Why |
|---|---|
| Written approval from your boss **and** whoever owns IT/security and data privacy | Spec requires IT/privacy requirements + signed scope before integration |
| Which data, which tables/columns, which period — **the minimum** | Data minimisation; start with a sanitized or aggregated extract |
| Whether the data contains personal/sensitive information | In the Philippines the Data Privacy Act (RA 10173) may apply — **ask their Data Protection Officer; I can't give legal advice** |
| Where it may be hosted (their cloud/VM vs. yours) | Spec: preferably customer-owned infrastructure |
| A **read-only** database account created by *their* IT | Spec: read-only source account, least privilege |
| Retention/deletion rule for anything you copy | Spec: retention/deletion policy |

### A2. Staged approach (recommended)
1. **Stage 0 — synthetic demo.** Show your boss the synthetic fixture dashboard (two rows → 300 / 120 / 40% / 2). No approval needed beyond showing it.
2. **Stage 1 — sanitized sample.** Client-approved extract with identifiers masked/removed, one report, one source (matches the paid-pilot scope). Run on **your own machine or a test VM**, not on their network.
3. **Stage 2 — read-only connection to a replica/reporting copy** (never the production OLTP database), on infrastructure *they* approve, behind their VPN/allow-list, with their IT present for the access, revocation and restore tests.
4. **Stage 3 — real users.** Only after IT signs off the checklist in Part D.

### A3. Don'ts
- Don't paste credentials, connection strings or data into chat tools (including this one). The stack reads secrets from a local `.env` / secret manager.
- Don't connect with an admin, owner or write-capable database account.
- Don't expose any BI port to the internet; don't test from a shared/public machine.
- Don't leave the demo running after the test; destroy volumes (`docker compose down -v`) and confirm with IT.
- Don't promise "secure" or "savings" to the client — the spec forbids that guarantee.

---

## Part B — Source database (read-only) **[VERIFIED]**

The role used in tests is created by `scripts/load_data.sh`. For a client, have **their DBA** create the equivalent:

```sql
CREATE ROLE insightflow_ro LOGIN PASSWORD '<from their secret manager>' NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT CONNECT ON DATABASE <db> TO insightflow_ro;
GRANT USAGE ON SCHEMA <schema> TO insightflow_ro;
GRANT SELECT ON <only_the_agreed_tables> TO insightflow_ro;        -- table-level, not ALL TABLES, for real clients
ALTER ROLE insightflow_ro SET default_transaction_read_only = on;  -- second layer
```

Evidence (`source_verification.json`): INSERT/UPDATE/DELETE/DROP/CREATE/TRUNCATE are all denied, **and** still denied when the session read-only flag is switched off — the grants alone protect the data. (The flag is a backstop, not the control.)
Also: restrict the DB to your server's IP; require TLS to the DB **[TODO — tests used plain loopback]**.

---

## Part C — Configuration, layer by layer

### C1. Network & edge **[TODO — design; not built]**
- Only the **reverse proxy** is reachable. Superset, Redis, the metadata DB and the source DB are on a private network.
- Bind containers to loopback or the private network (the repo's compose files bind to `127.0.0.1` **[CONFIGURED]**).
- HTTPS everywhere + HSTS; set `SS_COOKIE_SECURE=true` **[CONFIGURED flag, untested over HTTPS]**.
- **Path allow-list at the proxy**: route only the portal and the Superset paths the embedded view needs (`/embedded/*`, chart-data API, static assets). Do **not** route Superset's `/login`, `/api/v1/security/login`, SQL Lab, admin pages. Superset admin work happens over VPN/SSH tunnel.
- **Rate-limit and throttle logins at the proxy.** Reason **[VERIFIED GAP]**: Superset showed no login lockout on either login path (12–20 bad attempts, all accepted for processing). Also note Superset's own global limit is 50 req/s per IP (HTTP 429 observed) — pass the real client IP (`X-Forwarded-For`; `ENABLE_PROXY_FIX=True` is set **[CONFIGURED]**).
- If you ever use Metabase instead: block `/api/embed/**/csv|xlsx|json` at the proxy (export through a valid token works in OSS **[VERIFIED LIMITATION]**).

### C2. Identity — who is allowed in **[TODO]**
- The **portal** authenticates users via OIDC/SAML against the customer's identity provider (Microsoft Entra, Google Workspace, Keycloak…). **Enforce MFA at the IdP.** Neither engine's login is used by end users. *No IdP login has been tested yet.*
- Portal session: short idle timeout, secure/HttpOnly/SameSite cookies, server-side revocation list.
- Break-glass admin accounts (Superset admin) only via VPN, unique strong passwords, never shared.

### C3. Superset authorization — least privilege **[VERIFIED]**
1. **Never give end users Gamma/Alpha.** Stock Gamma includes `can_write` on charts and dashboards, `can_csv`, `can_explore_json` and user-registration permissions.
2. Use **guest tokens**; the guest role (`InsightFlowGuest`) has exactly **11 permissions**, no datasource access, no SQL Lab, no export, no explore (full list in `evidence/superset_embedding.json`). The only writes granted are `DashboardFilterStateRestApi` / `DashboardPermalinkRestApi` (dashboard UI state) — an accepted, documented trade-off.
3. If you also keep direct logins (e.g., for admins/analysts), use roles like `IF_SalesViewer` (23 permissions) and set **dashboard roles** (`DASHBOARD_RBAC=True`) so a dashboard is visible only to its role.
4. A stock viewer with no grants sees **nothing** (default-deny **[VERIFIED]**); still delete any stray content a low-privilege user managed to create (one chart was created with HTTP 201 during the baseline).

### C4. Guest tokens & row-level security **[VERIFIED]**
The portal API (not the browser) calls `POST /api/v1/security/guest_token/` with Superset credentials and sends the browser only the resulting token:
```json
{"user": {"username": "<portal user id>"},
 "resources": [{"type": "dashboard", "id": "<embedded uuid>"}],
 "rls": [{"dataset": <id>, "clause": "branch = 'Makati'"}]}
```
- `GUEST_TOKEN_JWT_EXP_SECONDS = 300` **[CONFIGURED + token claims verified: ttl 300 s]**. Superset applies **no clock leeway** (expired-by-1s token rejected) **[VERIFIED]**.
- Tested and rejected: wrong secret, `alg=none`, expired, tampered `resources`, stripped RLS, access to another dashboard's dataset, ad-hoc query on an unassigned raw dataset, CSV export, admin endpoints.
- RLS bypass attempt (`branch IN ('Cebu')` inside a Makati token) returns no rows; totals equal the independent Makati total to the cent.
- **Build the RLS clause only from the portal's own assignment table**, never from user input (SQL-injection surface). **[TODO — Phase 2 code review item]**
- Set `allowed_domains` on each embedded dashboard **and** the CSP `frame-ancestors` allow-list to the portal origin only (`SS_PORTAL_ORIGINS`). Default Superset blocks cross-origin framing; the browser refused the iframe until this was configured **[VERIFIED]**.

### C5. Superset hardening settings (`docker/superset/superset_config.py`)
| Setting | State |
|---|---|
| `SECRET_KEY` from env; image **refuses to boot with the default** | [VERIFIED] |
| `GUEST_TOKEN_JWT_SECRET` from env, ≥ 64 hex chars | [CONFIGURED] |
| `WTF_CSRF_ENABLED=True` | [CONFIGURED]; CSRF gotcha: viewer role needs `SecurityRestApi:can_read` or writes fail with 400 |
| `SESSION_COOKIE_HTTPONLY/SAMESITE`, `SESSION_COOKIE_SECURE` (env) | [CONFIGURED] |
| `PERMANENT_SESSION_LIFETIME` (default 480 min here) | [CONFIGURED, not time-tested] |
| `AUTH_RATE_LIMITED`, `AUTH_RATE_LIMIT` | [CONFIGURED but **NOT EFFECTIVE** — verified gap; use proxy] |
| `RATELIMIT_APPLICATION` global per-IP limit (env `SS_RATELIMIT`, default 50/s) | [VERIFIED active] |
| Source DB connection: `expose_in_sqllab=False`, `allow_dml=False`, `allow_ctas/cvas/file_upload=False` | [VERIFIED] |
| Connection password encrypted at rest; API omits/masks it | [VERIFIED] |
| Pin the image by digest, not `latest`; run vulnerability scan | [TODO] |

### C6. Secrets **[VERIFIED for the repo, TODO for production]**
- No secret is in source control: `scripts/init_env.sh` generates a local gitignored `.env` (mode 600) with random values. A scan of everything that could be committed found **no `.env` value** in any file **[VERIFIED]**.
- Production: use the customer's secret manager / injected environment variables; rotate on handover; never embed credentials in images or docs.
- Scan results: the five secrets I looked for (source password, user passwords, `SECRET_KEY`, guest secret, embed secret) were **absent from container logs and Superset's action-log API** **[VERIFIED]** — re-check after any log-level change (Metabase was running at DEBUG).

### C7. Audit & monitoring
- Superset's action log records per-call actor, dashboard, chart, duration — but **no login/logout events** and not denied attempts **[VERIFIED GAP]**.
- Therefore the **portal must write its own audit trail**: logins (success/failure), report views (user → report → time), admin changes (assign/revoke), refresh outcomes. Protect it (append-only, access-controlled) and keep secrets out **[TODO — FUNC-17]**.
- Also alert on: failed refresh, repeated 401/403 from one user/IP, token-mint spikes.

### C8. Backups & recovery **[TODO — TC-13 not run]**
Encrypt backups; test restore into an isolated instance and compare counts, settings and permissions; document the incident/rollback plan with IT.

---

## Part D — Acceptance checklist for IT (use for Stage 3)

Re-run these and attach the evidence (the repo's scripts already do the first five on synthetic data):
- [ ] Read-only role cannot write or create anything (`scripts/verify_source.py`).
- [ ] A viewer assigned report A **cannot** read report B by direct URL, API, chart-data call, or search (`ss_04_security.py hardened`).
- [ ] Revoking a user or assignment cuts access on the **same** live session (`ss_04_security.py revocation`) and the token TTL window is documented.
- [ ] Forged / expired / tampered tokens are rejected (`ss_06_embedding.py`).
- [ ] Row-level scope returns exactly the independent subset total.
- [ ] Reports reconcile to source totals to the cent (`ss_03_functional.py`) with agreed rounding.
- [ ] HTTPS only; no BI port reachable except via the proxy; HSTS present.
- [ ] Login throttling works **at the proxy** (the engine's does not).
- [ ] Export/download disabled unless explicitly authorized.
- [ ] Audit log shows logins, report views and admin changes, with no secrets.
- [ ] Backup restored in isolation: counts, settings and permissions match.
- [ ] Support limits, retention and responsibility transfer written down and signed.

## Part E — If Metabase is chosen instead (hardening delta)
Its defaults are **open** (**[VERIFIED LEAK]**: any new user could read all dashboards, run raw SQL, create content). Before use: set `All Users` collections to *none* and data access to *view-data unrestricted + create-queries no + download none* (script: `mb_04_security.py harden`), set `MB_ENCRYPTION_SECRET_KEY`, `MB_SESSION_SECRET_KEY`, `MAX_SESSION_AGE`; always set a short `exp` on embed tokens in **epoch seconds**; assume a 60 s expiry leeway; block export paths at the proxy; and remember embedded views are anonymous in Metabase's own logs.
