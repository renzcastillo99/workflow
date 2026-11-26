# InsightFlow BI — Microsoft Entra login + "free but secure" stack

Decision input from owner (26 Nov 2026): **identity provider = Microsoft; goal = as free as possible while still secured.**
Tags: **[VERIFIED-SRC]** = confirmed from Microsoft documentation this session · **[VERIFIED-P1]** = I tested it in Phase 1 · **[PROPOSED]** = open-source tool I would use, *not yet tested* · **[ASK IT]** = depends on the customer's tenant.
No tenant was contacted; no Entra login has been tested.

---

## 1. What Microsoft gives you for free (and what it doesn't)

| Capability | Entra ID Free | Needs paid (P1/P2) |
|---|---|---|
| Included with any Microsoft 365 / Azure subscription | Yes **[VERIFIED-SRC]** ([licensing](https://learn.microsoft.com/en-us/entra/fundamentals/licensing)) | |
| Sign-in for custom apps via OpenID Connect | Supported; Microsoft documents OIDC/OAuth/SAML as SSO options ([SSO planning](https://learn.microsoft.com/en-us/entra/identity/enterprise-apps/plan-sso-deployment)). Registering an app is reported to cost nothing (Microsoft Q&A answer, not official docs) — **confirm with IT** | |
| MFA for **all users** via **Security defaults** | Yes, no licence, on/off only; **Authenticator app only**; also blocks legacy auth ([security defaults](https://learn.microsoft.com/en-us/entra/fundamentals/security-defaults)) **[VERIFIED-SRC]** | |
| MFA only for *one app*, by location/device/risk (**Conditional Access**) | **No** | P1 (risk-based: P2) ([MFA licensing](https://learn.microsoft.com/en-us/entra/identity/authentication/concept-mfa-licensing)) **[VERIFIED-SRC]** |
| Security defaults **and** Conditional Access together | Not possible — they are mutually exclusive **[VERIFIED-SRC]** | |
| Assign *groups* to an app; app roles on Free | **Not confirmed** — I could not verify this | **[ASK IT]** |

**Consequence:** on the free tier you can get strong, free MFA, but it is **tenant-wide** (all your boss's staff, not just InsightFlow users). That is an IT decision, and many tenants already run Security defaults or Conditional Access. **Do not change tenant security settings yourself; ask IT what is already on.**

---

## 2. Login design that stays free (Phase 2 target)

**Entra answers "who are you" (authentication). The portal decides "what may you see" (authorization).** This keeps authorization out of Entra's paid features and matches the spec's user-management requirement (FUNC-12).

1. **Single-tenant app registration** in your boss's tenant, "web" redirect URI = the portal's HTTPS callback. Supported accounts: *this organisation only*. **[ASK IT to create it]**
2. **Authorization-code flow with PKCE**, confidential client (server-side secret/certificate). Permissions: only the sign-in basics (`openid`, `profile`, `email`) — **no application permissions, no admin consent beyond sign-in**. **[PROPOSED]**
3. Portal validates the ID token fully: signature via Microsoft's published keys, `iss`, `aud`, `exp`, `nonce`, and **`tid` = your boss's tenant id**. Use the stable object id (`oid`) as the user key — **not** the email address. **[PROPOSED]**
4. **Authorization lives in the portal's own database**: admin/viewer role, report assignments, revoke. A person who authenticates but has no assignment sees nothing (default-deny, same behaviour I verified in Superset **[VERIFIED-P1]**).
5. On the enterprise app, enable **"Assignment required"** so only people IT assigns can sign in at all. Per-user assignment is the part I expect to be free; **group** assignment may not be **[ASK IT]**.
6. **Require the MFA claim in the portal** as a free backstop for the missing Conditional Access: reject sign-ins whose token does not show MFA was performed (`amr` claim). **[PROPOSED — must be verified against a real tenant; I have not confirmed which claim Entra emits by default.]**
7. The portal then mints the 5-minute, row-scoped Superset guest token exactly as tested **[VERIFIED-P1]**. Superset's own login is never exposed.
8. Sessions: short idle timeout; sign-out clears the portal session; when IT disables a user in Entra, the portal still honours the old session until it expires → keep the portal session short (e.g., ≤ 1 h) and re-check with Entra at renewal. **[PROPOSED]**

What to ask IT to supply (spec's "Before integration" list): tenant id, app (client) id, a client secret or certificate **with an expiry date**, the redirect URI, the list of authorised users, and written approval.

---

## 3. Free-stack bill of materials

| Layer | Choice | Cost | Status |
|---|---|---|---|
| BI engine | Apache Superset 6.1 (Apache-2.0) | Free | **[VERIFIED-P1]** |
| Databases / cache | PostgreSQL 16, Redis 7 | Free | **[VERIFIED-P1]** |
| Packaging | Docker / Docker Compose | Free | **[VERIFIED-P1]** |
| Portal | React + TypeScript, FastAPI, Authlib or MSAL for Python | Free | [PROPOSED] |
| Ingestion | Python + Polars + a scheduler | Free | [PROPOSED] |
| Reverse proxy + HTTPS | Caddy or nginx; certificates from Let's Encrypt (needs a public DNS name) or the customer's internal CA | Free (domain/DNS may cost) | [PROPOSED] |
| Login throttling | proxy rate-limit rules, optionally fail2ban | Free | [PROPOSED] — needed because Superset's own throttle didn't work **[VERIFIED-P1 gap]** |
| Secrets | Docker secrets / SOPS + age, or the customer's own vault | Free | [PROPOSED] |
| Image + web scanning | Trivy (images), OWASP ZAP (web) | Free | [PROPOSED] |
| Backups | `pg_dump` + restic to customer storage; restore tested in isolation | Free (storage may cost) | [PROPOSED] |
| Monitoring | Uptime Kuma, container logs | Free | [PROPOSED] |
| Identity | Entra ID Free + Security defaults | Free **if the tenant allows it** | [VERIFIED-SRC] |

**Not free, can't be avoided:** the server/VM (ideally the customer's), a domain name if you want publicly-trusted HTTPS, your time. **Conditional Access / per-app MFA** and possibly group assignment would need Entra P1 — I did not look up prices. I'd skip them unless IT already has them.

**Still-open licensing item:** I have not checked licences of Superset's transitive dependencies or of the proposed tools above.

---

## 4. Because it is a Microsoft shop — check this *before* building

The approved process (SP-01 FIND, review step) says: **recommend the existing solution instead if it is more economical or suitable.** A Microsoft 365 company may already own **Power BI** (Pro/Premium, sometimes bundled) and keeps data in **SQL Server / Excel / SharePoint**. Ask what they pay today and what viewers cost; if Power BI already covers it, the honest recommendation may be "use what you have." That's also exactly the cost comparison your offer is built on (INC-01).

If they do want this portal and the source is **SQL Server**: Superset needs a SQL Server driver (not in the image; I only added Postgres) and a **read-only SQL login** created by their DBA. **[PROPOSED — not tested; TC-04 must be re-run against SQL Server.]**

---

## 5. Hosting and "secured" checklist for a free setup
1. Run on a VM the customer approves (their Azure/on-prem), not your laptop, for anything beyond a sanitized sample.
2. Only the reverse proxy is reachable; Superset/Postgres/Redis are internal-only (already loopback in the repo's compose files).
3. HTTPS + HSTS; secure cookies on (`SS_COOKIE_SECURE=true`).
4. Read-only database login, table-level grants only.
5. Entra: single tenant, assignment required, MFA enforced (tenant Security defaults, or IT's existing policy), MFA claim checked in the portal.
6. Short guest-token TTL (≤ 300 s); short portal session.
7. Portal audit log (logins, report views, admin changes, refresh outcomes).
8. Block exports unless authorised; restore test with IT; written support limits.

Full detail and the verified evidence: `SECURITY_CONFIGURATION.md`.
