# InsightFlow BI — Mini testable portal (Phase 2)

**What this is:** a working, clickable mini version of the portal so you can *see* the approved features. Synthetic data only. **Not production software** and not the full application.
**Stack (all free):** FastAPI portal · Apache Superset 6.1 (embedded) · PostgreSQL · Keycloak (free local login server with MFA) · Docker.
**Login:** standard OpenID Connect. Keycloak stands in for your boss's identity provider; switching to Microsoft Entra later is a settings change (section 8) — **Entra itself is untested**.

---

## 1. What you can click through

| Screen (spec ID) | Try this | What you should see |
|---|---|---|
| **Sign in** (UI-01) | Open `http://127.0.0.1:9000` → *Sign in* | Redirect to the identity provider; password **then** an authenticator code (MFA). Wrong password/code → refused. |
| **Overview** (UI-02) | Sign in as a viewer, then as the admin | Viewer: only their reports + freshness. Admin: also an operational summary (users, rejected refreshes, denied events). |
| **Assigned reports** (UI-03) | Search box; open a report | Only reports assigned to you are listed. |
| **Report** (UI-04, FUNC-09) | Open *Sales report (live data)* | KPI cards, trend, branch chart, branch table, filters, and **"Last successful refresh"**. Numbers are served by Superset through a short-lived token. |
| **Row scope** | Sign in as *Mia Makati* | She sees **only Makati** figures; the badge says "Scope: Makati". |
| **Permission denied** (FUNC-08) | As a viewer, type `/reports/finance-check` in the address bar | "Permission denied" page; same answer for a report that doesn't exist. |
| **Data sources** (UI-05, FUNC-03/04) | Admin → *Data sources* → upload `data/samples/snapshot_v2_plus5.csv` | Validated, reconciled, published; viewers see new numbers. Try the `bad_*.csv` files and `malformed.xlsx` → rejected with line-by-line reasons; **live data unchanged**. |
| **Refresh history** (UI-06) | Admin → *Refresh history* | Every job, status, row counts, rejected rows. A second upload during a running one is refused. |
| **User management** (UI-07, FUNC-12) | Admin → *User management* | Add user, assign/revoke a report (with branch scope), deactivate/re-activate. Revocation is immediate for new requests and sessions. |
| **Audit logs** (UI-08, FUNC-17) | Admin → *Audit logs* | Sign-ins, denied attempts, report views, admin changes, refresh outcomes. Filter by outcome. No secrets. |
| **Settings** (UI-09, FUNC-14) | *Settings* | Light/dark theme (remembered), account info, sign out. |
| **Responsive** (FUNC-15) | Narrow the browser window | Menu collapses; pages fit. Reports scroll sideways inside their frame on a phone (see limits). |

## 2. Demo accounts
Created by `scripts/p2_03_keycloak.py` into **`docker/keycloak/demo_accounts.txt`** (gitignored — password and an authenticator secret for each; Microsoft Authenticator or any TOTP app works).

| User | Role in the portal | Can open |
|---|---|---|
| `admin.demo` | Administrator | everything + admin screens |
| `viewer.sales` | Viewer | Sales report (all branches) |
| `viewer.makati` | Viewer | Sales report **and** Large dataset, **Makati only** |
| `viewer.none` | Viewer | nothing yet (shows the empty state) |
| `stranger.demo` | *not provisioned* | can sign in at the IdP but the **portal refuses** them |

## 3. Run it yourself
**You need:** Docker Desktop (running, with at least 8 GB RAM given to it), Git, Python 3.10+, and free ports **8088, 8180, 9000, 15432**. On **Windows use WSL2 (Ubuntu)** and run everything inside it; plain PowerShell/Git Bash is not supported. First run downloads about 4 GB and takes roughly 10-20 minutes.
Each step was run in this environment; the *whole sequence has not been executed from scratch on a clean machine*, so expect to fix small things.

```bash
# 1. get the code
git clone https://github.com/renzcastillo99/workflow.git && cd workflow
git checkout claude/cool-johnson-hpr3fc && cd insightflow-feasibility

# 2. Python environment (one venv used by the portal AND the setup scripts)
python3 -m venv portal/.venv && portal/.venv/bin/pip install -r portal/requirements.txt
export PY=$PWD/portal/.venv/bin/python

# 3. local secrets (random, gitignored) and the shared Docker network
docker network create ifnet
./scripts/init_env.sh && ./scripts/p2_00_env.sh

# 4. synthetic data + database
$PY scripts/gen_data.py                                   # about 230 MB, ~20 s
docker compose --env-file .env -f docker/data.compose.yml up -d
./scripts/load_data.sh

# 5. Superset (builds the image, initialises it, waits until it answers)
./scripts/ss_00_init.sh
(cd scripts && $PY ss_01_setup.py && $PY ss_02_content.py)

# 6. the mini-portal pieces
./scripts/p2_01_db.sh                                     # serving schema + 20,000 live rows
$PY scripts/p2_02_superset.py                             # live dashboard, embedding, token-only service account
$PY scripts/p2_03_keycloak.py                             # login-server realm + demo accounts
docker compose --env-file .env -f docker/keycloak.compose.yml up -d     # wait ~30 s

# 7. seed and start the portal (the Superset embed file portal/static/sdk.js is already in the repo; no Node needed)
(cd portal && .venv/bin/python seed.py && ./run.sh)
$PY scripts/p2_samples.py                                 # upload test files -> data/samples/
```
**Then open `http://127.0.0.1:9000`** (use `127.0.0.1`, **not** `localhost` — the login and embedding settings are tied to it).
**Sign in:** username e.g. `viewer.sales`; password is in `docker/keycloak/demo_accounts.txt`; for the 6-digit code run `$PY scripts/p2_totp.py viewer.sales` (or add the base32 secret from that file to an authenticator app). Codes can't be reused: if a login fails, wait for the next 30-second window.
**Back to the starting state:** `./scripts/p2_reset.sh`. **Stop:** `pkill -f "uvicorn app:app"` and `docker stop $(docker ps -q)`.
**If something fails:** `docker ps` (all of `if-data-pg`, `if-superset`, `if-keycloak` should be running), `docker logs if-superset`, and `portal/data/portal.log`. Docker Hub can rate-limit pulls (HTTP 429); wait a minute and re-run the step.

## 4. Test evidence (synthetic data; one VM; `evidence/`)
| Suite | File | Result |
|---|---|---|
| Access, scoping, revocation, sessions, CSRF, theme, contrast, keyboard, mobile — real browser, real login with MFA | `p2_e2e_access.json` | **93 PASS, 0 FAIL**, 3 flagged (1 inconclusive, 2 info) |
| Upload → validate → reconcile → atomic publish, last-good preserved, no overlap, audit, secrets scan | `p2_e2e_data.json` | **64 PASS, 0 FAIL** |
| Identity-provider brute-force lockout | `p2_e2e_idp_lockout.json` | **2 PASS** |
Run them: `node scripts/p2_e2e_a.cjs`, then `p2_e2e_b.cjs`, then `p2_e2e_c.cjs` (A and B must run back to back; reset first). Screenshots: `evidence/screenshots/p2_*.png`.

Highlights (each is a test, not a claim): viewer sees only assigned reports and direct URLs/API return 403 · Makati token returns only Makati figures even when asked for Cebu · revoking an assignment denied the same live session in ~0.65 s · deactivating a user ended their session in ~0.6 s and a replayed old cookie was rejected · 4 bad files rejected and live totals stayed exact to the cent · **866 concurrent BI reads during a publish saw only the old or the new snapshot, 0 errors** · a second refresh during a 500,000-row job was refused (that job took 5.7 s end to end) · no secret or token found in the audit log, job history or server log.

## 5. Bugs the testing found (all fixed unless noted)
1. **Embedded reports returned 403 for everyone.** My portal sent `Referrer-Policy: same-origin`, and Superset validates the embedding origin from the `Referer`. Fixed (`strict-origin-when-cross-origin`). I first missed this because I read only the end of a long log.
2. **`X-Frame-Options: DENY` silently disappeared** after my own edit commented it out; a test caught it. Headers are now one per line.
3. **After a publish, viewers could see old numbers for up to 5 minutes** while the job said "BI cache refreshed". Two Superset settings were needed for cache invalidation to work at all: `STORE_CACHE_KEYS_IN_METADATA_DB = True`, and the chart-data cache must share the same Redis DB/prefix as the general cache. Proven both directions (stale → invalidate → correct). A 60-second dataset cache timeout is a backstop.
4. **Mobile menu trapped itself** (the open menu covered its own toggle). Added a Close button + Escape.
5. **Token service account** needed one extra read permission (CSRF) — still can do only: mint tokens, invalidate cache.
6. Test-harness issues I fixed along the way: TOTP codes can't be reused (login helper now retries on a fresh window); Keycloak imports every file in its folder; a racy margin check; my lockout test left an account locked for the next run (reset now clears lockouts). One design fix: the no-overlap lock now covers the whole refresh job, not only the publish step.

## 6. What the mini does NOT do (still to build)
- **Scheduled refresh** and the **SQL-source connector UI** (refresh here is a manual upload; atomic publish, no-overlap and keep-last-good are real).
- **Email/push alerts** — failures are shown on screens and in history only.
- **Per-customer deployment automation, backup/restore, handover guides, IT acceptance pack.**
- **HTTPS/HSTS, vulnerability scans, rate limiting at a proxy** (everything runs on HTTP loopback). Superset is reached directly by the browser here; production routes it through a path allow-list proxy.
- **Mobile report layout:** Superset's fixed grid is not phone-friendly; the mini lets the report scroll sideways in its frame. A proper single-column layout is future work.
- **Inter font file** is not bundled (system fallback is used); Superset chart colours are still its default teal.
- **MFA is enforced by the identity provider only.** Keycloak's tokens carry no MFA claim, so the portal cannot independently verify it.
- **Portal DB is SQLite** (PostgreSQL in the full build). **Revocation window:** an already-open report keeps its data until its 5-minute guest token expires.
- Everything is tested on **synthetic data**; no real or company data was used.

## 7. Security design in one paragraph
The identity provider proves who you are (password + authenticator). The portal alone decides what you may see (its database, default-deny). Server-side sessions (30 min idle / 8 h max) are deleted on sign-out or deactivation. The browser never holds a Superset credential: the portal mints a 5-minute token for exactly one dashboard, with the row filter taken from your assignment. The Superset service account can only mint tokens and invalidate cache. The BI engine reads one read-only schema; the ingest role can write only to `live`/`staging`; the source system is never written to.

## 8. Moving to Microsoft Entra (not yet tested)
Set these environment variables instead of the Keycloak defaults (names are in `portal/config.py`): `OIDC_ISSUER=https://login.microsoftonline.com/<tenant-id>/v2.0`, `OIDC_CLIENT_ID`, `OIDC_CLIENT_SECRET`, `OIDC_REQUIRED_TID=<tenant-id>`. The portal already identifies users by `oid`, requires them to be pre-provisioned, and can reject sign-ins without an MFA claim (`REQUIRE_MFA_CLAIM=true`) — **verify that claim against a real tenant before relying on it.** IT must create the app registration (redirect URI `<portal>/auth/callback`).
