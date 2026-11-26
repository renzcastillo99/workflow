# InsightFlow BI — Phase 1 Technical Feasibility Report

**Scope:** Metabase (open-source) vs Apache Superset against the approved spec (licensing, security, private report access, theming, performance).
**Status of this document:** Phase 1 only. No portal, ingestion or refresh code has been built. Nothing below is a production claim.
**Data:** 100% synthetic (spec fixture + generated 100k / 500k / 1M / 5M rows). **No real or boss's-company data was touched.**
**Tested on:** one 4 vCPU / 15 GiB VM running the BI engine, its metadata DB, the source Postgres *and* the load generator together, over loopback. Dates: 25–26 Nov 2026.
**Versions tested:** Metabase OSS `v0.65.7.2` (`metabase/metabase:latest`, AGPL image) · Apache Superset `6.1.0` (`apache/superset:latest`, plus Postgres driver and Authlib added) · PostgreSQL 16.

---

## 1. Verdict

| | |
|---|---|
| **Recommended engine** | **Apache Superset 6.1.0** behind a custom portal (portal authenticates users; Superset only ever sees short-lived **guest tokens** with per-token row-level security). |
| **Fallback** | Metabase OSS, *only* if the client accepts a permanent "Powered by Metabase" banner, default Metabase look (Lato font, default colours), and you accept the AGPL review below — or buys a Metabase commercial licence (price **not verified**, see §3). |
| **Stop condition in spec** ("stop if no lawful, secure, feasible option") | **Not triggered.** Superset is Apache-2.0 and passed the private-access, RLS, revocation and embedding tests. |
| **Ready for full build?** | **No — awaiting your approval of the architecture in §7.** Several items remain unverified (§9). |

Why Superset wins *on your approved requirements* (not on raw speed — Metabase was faster under load):

1. **Theming requirement is met only by Superset.** Metabase OSS refuses brand colours, font and logo (HTTP 402 "whitelabel not available") and shows a mandatory "Powered by Metabase" banner in embeds. Superset applied your exact tokens (Inter stack, `#1E293B` dark surface, `#F1F5F9` canvas) and shows no vendor branding when embedded.
2. **Row-level security is free in Superset**, and per token. Metabase's equivalent (sandboxes) is a paid feature; Metabase OSS can only scope with a *locked* URL parameter in a signed token.
3. **Deny-by-default.** A brand-new stock Superset viewer sees nothing. A brand-new **Metabase** user could read every dashboard and run raw SQL (§4.1).
4. **Licence is simpler** (Apache-2.0 vs AGPL + commercial split).

What Superset costs you: heavier operations (Redis, gunicorn tuning), a custom image, more configuration to get least-privilege right, no mobile-responsive embed without extra layout work, and worse tail latency under a 20-viewer burst (§5).

---

## 2. What was actually run (evidence index)

Every number here comes from a script in `scripts/` and a JSON file in `evidence/` (summary: `evidence/SUMMARY.md`). Statuses: **PASS**, **FAIL**, **GAP** (a real weakness found), **LIMITATION** (feature absent/behaves differently), **LEAK-REPRODUCED** (insecure default confirmed), **INFO**, **INCONCLUSIVE**.

| Area | Evidence file(s) | Result |
|---|---|---|
| Source data + DB-level read-only | `source_verification.json` | 18/18 PASS |
| KPI accuracy (Metabase) | `metabase_functional.json` | 10/10 PASS |
| KPI accuracy (Superset) | `superset_functional.json` | 10/10 PASS |
| Metabase authz: defaults / hardened / revocation | `metabase_security_{baseline,hardened,revocation}.json` | baseline **LEAK-REPRODUCED ×10**; hardened 15/15; revocation 7/7 |
| Superset authz: defaults / hardened / revocation | `superset_security_{baseline,hardened,revocation}.json` | 13/13; 22/22; 9/9 |
| Metabase embedding (adversarial) | `metabase_embedding.json` | 17 PASS, 5 LIMITATION |
| Superset embedding (adversarial) | `superset_embedding.json` | 21 PASS, 3 INFO, 2 INCONCLUSIVE |
| Metabase OSS capability probes | `metabase_oss_capabilities.json` | 14 LIMITATION, 1 INFO |
| Misc security / audit / secrets | `superset_misc_security.json`, `at_rest_and_audit.json`, `metabase_login_throttle.json`, `metabase_session_expiry.json` | 2 GAP, 1 LIMITATION (see §4) |
| Performance | `metabase_benchmark.json`, `superset_benchmark.json`, `postgres_direct_attribution.json` | §5 |
| Visuals | `evidence/screenshots/*.png` | §6 |

**Spec "first test"** (two-row fixture + unauthorized direct request): done on both engines. Fixture → **300 / 120 / 40% / 2**; filtered to first row → **100 / 40 / 40% / 1**; zero-revenue margin → **undefined (null), not 0**; unassigned dashboard/card/query/SQL → **denied (403/404)**.

---

## 3. Licensing

| | Metabase | Superset |
|---|---|---|
| Licence of what I ran | **AGPL** (`metabase/metabase` image). Source repo `LICENSE.txt`: files outside `enterprise/` are AGPL; `enterprise/` and the `metabase-enterprise` image are under the Metabase Commercial License. *(Read from the vendor repo.)* | **Apache-2.0** (`LICENSE.txt` and `NOTICE` read from the Apache repo). |
| Paid features observed missing in the running OSS instance | `/api/session/properties` reported **zero** token features. Probed with real calls: whitelabel (402), SAML/JWT SSO (unknown setting), MFA (402), password-login disable (402), sandboxes/row-level (404), audit app (404), advanced permissions (404). | n/a — RLS, guest tokens, theming, RBAC all worked unpaid. |
| Embedding | Static (signed) embedding works in OSS. **"Powered by Metabase" banner is shown** (screenshot + DOM link). I found no OSS setting to hide it. | Embedded SDK / guest tokens work unpaid. No vendor banner in the embedded view. |
| Pricing of Metabase paid tiers | **NOT VERIFIED** — `metabase.com` was unreachable from this sandbox. | n/a |

**Not legal advice.** AGPL obligations when you ship a per-customer Docker stack and run it for clients are a question for counsel *before* choosing Metabase. Also not audited: licences of transitive dependencies in either product.

Spec rule "no licensing workaround": removing Metabase's banner or enabling its paid features without a licence would violate it — I did not attempt that.

---

## 4. Security findings

### 4.1 Default posture (this matters for your test)

| Check (as a freshly created, ungranted viewer) | Metabase defaults | Superset (stock Gamma) |
|---|---|---|
| Read an unassigned dashboard / card | **Allowed (200)** | Denied (404) |
| Run arbitrary native SQL against the source | **Allowed — returned rows** | Denied (403) |
| Run ad-hoc query on a 5M-row raw table | **Allowed** | Denied (403) |
| Create content | **Allowed** | **Allowed (201)** on a dataset with no access — cleaned up |
| See unassigned titles in search / list | **Yes** | No |
| See data-source list | Yes | No |

Root cause on Metabase: the **All Users** group ships with `write` on every collection and `query-builder-and-native` + full download on the database. **Both engines must be hardened; Metabase far more urgently.** Hardened re-runs of the identical probes: Metabase 15/15 fail-closed, Superset 22/22.

Superset's stock **Gamma is not a safe viewer role** (it carries `can_write` on charts/dashboards, `can_csv`, `can_explore_json`, user-registration permissions). I built a minimal role (23 permissions) and a minimal guest role (**11 permissions**, no datasource, SQL, export or explore grants — listed in `superset_embedding.json`). Gotcha found: without `SecurityRestApi:can_read` the UI cannot obtain a CSRF token.

### 4.2 Verified controls

| Control | Metabase OSS | Superset |
|---|---|---|
| Server-side denial of unassigned direct URL/API (TC-07) | ✅ after hardening | ✅ |
| Revocation takes effect on the *same live session* (TC-11) | ✅ deactivate → 401; group removal → 403 | ✅ deactivate → 401; role swap → 403/404 |
| Row-level scoping | Locked JWT param (OSS); real sandboxes paid | ✅ RLS rule per role **and** per guest token; bypass attempt (`branch=Cebu`) returned nothing |
| Signed-token tamper tests | wrong secret, `alg=none`, tampered payload, cross-dashboard, non-embedded dashboard → all rejected | wrong secret, `alg=none`, expired, tampered resources, stripped RLS → all rejected (control token re-signed with real secret accepted, proving tests valid) |
| Token expiry | Enforced, **but 60 s leeway** (measured: accepted 58 s past `exp`, rejected 62 s) | Enforced, **0 s leeway**; default TTL 300 s |
| Server-side session expiry (TC-06) | ✅ via `MAX_SESSION_AGE` env (1-min test → 401 at 75 s). The UI "session timeout" setting is **not enforced** | Not time-tested (JWT lifetime config not exercised) |
| Brute-force protection | ✅ lockout at attempt 11 | ❌ **GAP** — none on either login path (see below) |
| Source write denial (TC-04) | Read-only DB role: INSERT/UPDATE/DELETE/DROP/CREATE/TRUNCATE all denied; denial holds even if the session read-only flag is overridden (grants alone suffice) | same source |
| Source credentials at rest | Encrypted (needs `MB_ENCRYPTION_SECRET_KEY`); API masks | Encrypted column; API omits it, export masks `XXXXXXXXXX` |
| Secrets in logs | 5 secrets not found in container logs | 5 secrets not found in logs/action-log API |
| CSV/Excel/JSON export through the embed path | ⚠ **LIMITATION**: works through a valid token (200 ×3); OSS has no per-embed disable → block at reverse proxy | ✅ denied (403) — guest role has no export permission |
| Who-viewed-what audit | ⚠ **LIMITATION**: all 1,737 embedded query executions have `executor_id = NULL` | per-API-call log with user/dashboard/chart; ⚠ **GAP**: no login/logout events |
| Boot with default secret | — | ✅ Superset **refuses to start** with its default `SECRET_KEY` |

**Metabase pitfalls found while testing** (relevant if you ever use it): a token with **no `exp` never expires**; `exp` in **milliseconds** is accepted as a far-future date (never expires) — my first "expired token" tests were wrong, which is how I found the 60 s leeway; Metabase warns that without `MB_SESSION_SECRET_KEY` anyone with app-DB access can forge sessions.

**Superset gaps found:**
- **GAP — login throttling.** 12–20 bad attempts on `/login/` and `/api/v1/security/login`: no lockout. `AUTH_RATE_LIMIT` is loaded but the only limiter key in Redis is the global one. Root cause undiagnosed. Mitigate at the reverse proxy and keep Superset off the public internet.
- **Global limit 50 req/s per IP is on** (image sets `SUPERSET_ENV=production`): a burst got HTTP 429. Tunable (`RATELIMIT_APPLICATION`); behind a proxy make sure the real client IP is used.
- **Embedding is blocked by default.** Superset sends `X-Frame-Options: SAMEORIGIN`; the browser refused to render the iframe from the portal origin (captured). `allowed_domains` alone didn't change that. Fixed by dropping XFO and setting CSP `frame-ancestors 'self' <portal origin>` (now in `superset_config.py`); then the embedded dashboard rendered with exact, RLS-scoped values.
- **INCONCLUSIVE (honest):** guest-token calls to SQL Lab / create-chart returned CSRF 400, which masks the authz decision. Covered instead by inspecting the guest role's permission list.

**Not verified at all:** real identity-provider login (SAML/OIDC) against any IdP; Metabase Google sign-in end-to-end (setting accepted, flag says disabled); MFA (delegated to IdP by design); vulnerability scans; HTTPS/HSTS (everything ran on HTTP loopback); cross-instance isolation (TC-16); backup/restore (TC-13).

---

## 5. Performance (TC-17, synthetic, one VM)

Method: a "dashboard load" = the 7 cards fired in parallel (what a browser does), wall time = slowest card; via the **portal path** (signed embed token / guest token, no session). 15 runs per cell; p50/p95 shown. Postgres: `shared_buffers=1GB`, indexes on PK/date/branch, fully cached. Metabase query caching: off (default). Superset: Redis cache **bypassed** (`force=true`) in the primary rows for a like-for-like comparison.

| Rows | Metabase initial (p50 / p95) | Superset initial, cache bypassed | Metabase filter change | Superset filter change |
|---:|---|---|---|---|
| 100k | 324 / 364 ms | 447 / 477 ms | 113 / 147 ms | 245 / 327 ms |
| 500k | 1,381 / 1,478 ms | 1,593 / 1,776 ms | 109 / 120 ms | 258 / 281 ms |
| **1M** | 2,878 / **3,040 ms** | 3,132 / **3,414 ms** | 107 / 127 ms | 263 / 345 ms |
| 5M (exploratory) | 14,845 / 15,581 ms | 15,039 / 15,618 ms | 175 / 205 ms | 348 / 391 ms |

**20 concurrent viewers × 3 filtered dashboard loads (60 loads, 0 failures unless noted):**

| Rows | Metabase p50 / p95 | Superset, cache bypassed | Superset, **warm cache** |
|---:|---|---|---|
| 1M | 1,786 / 2,543 ms | 3,925 / 5,319 ms | 1,916 / 3,973 ms |
| 5M | 2,979 / 3,865 ms | 5,422 / 7,825 ms | 2,432 / 3,167 ms |

Superset warm-cache **single-user** latency: unfiltered ≈ 154–158 ms p50 (1M/5M); filtered ≈ 141–152 ms.

**Against your proposed targets (initial ≤ 3 s, filters ≤ 2 s, 20 viewers) — not guarantees:**
- Filters ≤ 2 s: **met by both** at every size (single user).
- Initial ≤ 3 s: **met ≤ 500k by both; at 1M marginally missed** (Metabase 3.04 s, Superset 3.41 s uncached); Superset passes with a warm cache (≈ 0.2 s). **5M: ~15 s on both — exploratory only.**
- 20 concurrent viewers: neither is comfortably within ~2 s p95 at 1M on this VM (Metabase 2.5 s; Superset 5.3 s uncached, 4.0 s warm). Superset's Python workers saturate on 4 shared vCPUs; this is the weakest result for the recommended engine.

**Attribution:** one KPI query straight on Postgres takes ≈ 0.4 s at 1M (EXPLAIN ANALYZE 415 ms, fully cached) and ≈ 1.7 s at 5M. A dashboard fires 7 queries at once, 4 of them full scans, so the unfiltered numbers are **source-DB-bound, not engine-bound** — the same wall for both engines. Mitigations to test in Phase 2: default date filter, pre-aggregated serving table, more cores, separate load generator, more Superset workers.

**Caveats:** single VM shared with the load generator; loopback network; uniformly random data; one dashboard shape; first-load is "first touch since start", not a true cold OS cache. Power BI benchmark **not run** (no authorized access).

Other accuracy evidence: both engines reproduced independent `Decimal` totals **to the cent** at 100k/500k/1M/5M and for a per-branch table (12 branches, exact), with margin undefined (null) at zero revenue. Note both return margin as an unrounded fraction (Metabase `0.3251280548831353`; Superset `0.4000000000…`) — **agreed rounding must be applied in the presentation layer**. Metabase KPI cards compact big numbers by default (`2.1B`), which loses precision; format explicitly.

---

## 6. Theming and responsiveness (TC-14 / TC-15, engine level only)

| Requirement | Metabase OSS embed | Superset embed |
|---|---|---|
| Inter font | ❌ Lato (custom font = paid) | ✅ font stack applied (whether the Inter file itself is bundled vs. falling back was **not independently verified**) |
| Primary `#2563EB`, spec palette | ❌ default `#509ee3`; brand-colour setting → 402 | ✅ tokens applied (canvas/surface/text/dark confirmed in computed styles). ⚠ **Chart series colours still default teal** — a custom colour scheme is not yet done |
| Light / dark | ✅ via `#theme=night` (dark bg `#071722`, not spec `#0F172A`) | ✅ via `superset-theme-mode`; dark surfaces exactly `#1E293B` / layout `#0F172A` |
| No vendor branding | ❌ "Powered by Metabase" | ✅ none in embedded view (standalone UI shows Superset logo) |
| Mobile 390 px | ✅ cards stack cleanly, no horizontal scroll | ❌ fixed grid collapses to squeezed, unreadable cards (no horizontal scroll, but unusable) — needs a dedicated single-column layout |
| Persisted preference, keyboard focus, contrast audit | **NOT TESTED** | **NOT TESTED** |

Screenshots: `evidence/screenshots/` (`mb_embed_*`, `ss_*`, `ss_embed_*`). *Visual ≠ implemented ≠ verified* — these show the engines' capability, not the InsightFlow portal.

---

## 7. Recommended architecture (for your approval)

```
                         Customer-owned cloud, ONE isolated stack per customer
 Browser ──HTTPS──► Reverse proxy  (TLS, HSTS, rate-limit + login throttling, path allow-list,
                         │          security headers, real-client-IP forwarding)
                         ├──► Portal SPA (React/TS) ◄──► Portal API (FastAPI)
                         │        • OIDC/SAML login against the customer's IdP (MFA enforced at IdP)
                         │        • admin/viewer RBAC, report assignments, user revoke  (portal Postgres)
                         │        • AUDIT LOG: logins, report views, admin changes, refresh outcomes
                         │        • mints Superset GUEST TOKEN server-side: TTL ≤ 300 s,
                         │          RLS clause from the assignment, exactly one dashboard
                         └──► allow-listed Superset paths only (/embedded/*, chart-data, static)
                                   │          (Superset admin UI, SQL Lab, REST login: NOT routed)
                                   ▼
                 Superset 6.1 (private net) + Redis cache + metadata Postgres
                                   │ read-only role
                                   ▼
                 SERVING Postgres (curated tables, per customer)  ◄── atomic publish ── staging schema
                                                                               ▲
   Ingestion / refresh worker (Python + Polars, scheduler, no overlap, job history, alert) ──┘
        inputs: XLSX · CSV · read-only SQL source (customer DB, read-only account, never written)
```

Why this shape:
- **Superset never authenticates end users.** The portal does, so SSO/MFA/audit live in one place we control, and Superset's weak spots (login throttling, no login audit) are not exposed.
- **Superset reads a serving DB, not the client's source.** Matches spec ("stage → validate → atomic publish; failed refresh keeps last verified snapshot") and protects the client's system from dashboard scan load.
- **Per-customer isolated stack** (spec: no multi-tenant service). Superset superuser credentials stay inside the portal API; the browser only ever holds a 5-minute guest token.
- **Revocation window = guest-token TTL (≤ 300 s)** + portal-side session invalidation; Superset has no leeway. Keep TTL short.

Phase 2 build order I'd propose (each gated by its test case): ① synthetic stack + minimal portal (OIDC against a local test IdP, token minting, one report) → TC-06/07/08/11; ② ingestion + atomic refresh → TC-02/03/04/09/10; ③ audit + admin screens → TC-12; ④ backup/restore + isolation → TC-13/16; ⑤ performance tuning → TC-17; ⑥ docs/handover → TC-18.

---

## 8. Requirement-by-requirement (Phase 1 slice)

| Spec requirement | Metabase OSS | Superset | Note |
|---|---|---|---|
| Lawful, no licence workaround | ⚠ AGPL + banner; counsel | ✅ Apache-2.0 | §3 |
| Private embedding + server-enforced authz incl. engine endpoints | ✅ after hardening | ✅ | §4 |
| Dedicated per-customer deployment | ✅ Docker | ✅ Docker | isolation test (TC-16) not run |
| KPI exactness, zero-revenue = undefined | ✅ | ✅ | §5 |
| Theme (colours, Inter, dark, no vendor mark) | ❌ | ✅ (chart palette TODO) | §6 |
| Responsive tablet/mobile | ✅ | ❌ without custom layout | §6 |
| Export disabled by default | ❌ needs proxy rule | ✅ | §4.2 |
| Row-level scoping | ⚠ locked param only | ✅ | |
| Performance targets | ≈ (1M initial marginal miss) | ≈ (1M miss uncached; weak under burst) | §5 |
| Audit / who-viewed-what | ❌ anonymous in embed | ⚠ per-call, no login events | portal must own audit |
| Established IdP login | not tested | not tested | portal responsibility; Phase 2 |

---

## 9. Not done / open risks (don't read past these)

1. **No real IdP tested.** FUNC-07 is unproven end to end.
2. **Superset concurrency** (20 simultaneous viewers) is the weakest measured result; needs tuning and a re-test on separate load-generator hardware.
3. **Superset mobile** layout and **chart palette / Inter bundling** are unresolved.
4. **Superset login throttling** gap — proxy mitigation designed, not built or tested.
5. **HTTPS, HSTS, secure cookies, vulnerability scan, incident/rollback plan** — nothing tested; everything ran on HTTP loopback.
6. **Excel/CSV ingestion, scheduled refresh, atomic publish, restore, cross-instance isolation** (TC-01/02/03/09/10/13/16/18) — **NOT RUN**; they belong to Phase 2.
7. **Metabase paid-tier pricing and AGPL implications** unverified.
8. Demand, pricing, savings: unvalidated (spec's own verdict: *VALIDATE FIRST*).
9. Superset's `latest` tag was used; pin exact image digests before any real deployment.

---

## 10. Reproduce

See `README.md`. All scripts read secrets from a local, gitignored `.env` generated by `scripts/init_env.sh`; none are committed.
