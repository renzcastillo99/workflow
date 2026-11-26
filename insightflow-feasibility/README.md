# InsightFlow BI — feasibility (Phase 1) + mini testable portal (Phase 2)

Evaluates **Metabase OSS** vs **Apache Superset** against the approved spec, using **synthetic data only**.
**Start with** `docs/FEASIBILITY_REPORT.md` (verdict, evidence, recommended architecture), then `docs/SECURITY_CONFIGURATION.md` and `docs/MICROSOFT_ENTRA_AND_FREE_STACK.md` (Microsoft login + free stack).
**Phase 2 (`portal/`, `docs/PHASE2_MINI_PORTAL.md`) is a clickable MINI portal** (login with MFA, assigned reports, row-scoped embedded dashboards, data upload with atomic publish, user management, audit log, light/dark). It is a mini demo on synthetic data, **not** the full application.

```
portal/      mini portal (FastAPI): app.py, ingest.py, superset.py, templates/, static/   (run with portal/run.sh)
docs/        FEASIBILITY_REPORT.md · SECURITY_CONFIGURATION.md · MICROSOFT_ENTRA_AND_FREE_STACK.md · PHASE2_MINI_PORTAL.md
evidence/    JSON results per test + SUMMARY.md + screenshots/   (this is the proof; read SUMMARY.md first)
docker/      data.compose.yml · metabase.compose.yml · superset.compose.yml · superset/{Dockerfile,superset_config.py}
scripts/     data generation, loaders, per-engine tests, benchmark harness, mini portal prototype (portal_proto/)
```

## Reproduce (needs Docker, Python 3, Node for screenshots)

```bash
docker network create ifnet
./scripts/init_env.sh                      # local gitignored .env with random synthetic secrets (nothing is committed)
python3 scripts/gen_data.py                # deterministic synthetic data + independent Decimal expectations
docker compose --env-file .env -f docker/data.compose.yml up -d
./scripts/load_data.sh                     # loads 2-row fixture, zero-revenue fixture, 100k/500k/1M/5M; creates READ-ONLY role
(cd scripts && python3 verify_source.py)   # TC-04/05 at database level
```

Metabase OSS (`cd scripts`): `docker compose --env-file ../.env -f ../docker/metabase.compose.yml up -d` → `mb_01_setup.py` → `mb_02_content.py` → `mb_03_functional.py` → `mb_04_security.py baseline | harden | hardened | revocation` → `mb_05_embedding.py` → `mb_06_bench.py`.

Superset (`cd scripts`): `./ss_00_init.sh` → `ss_01_setup.py` → `ss_02_content.py` → `ss_03_functional.py` → `ss_04_security.py baseline | harden | hardened | revocation` → `ss_06_embedding.py` → `ss_07_bench.py`.
Embedded-in-browser demo: `python3 portal_proto/server.py` (the SDK bundle `portal_proto/sdk.js` is included).
Finally `python3 finalize_evidence.py` normalises statuses and regenerates `evidence/SUMMARY.md`.

## Phase 2 quick start
See **`docs/PHASE2_MINI_PORTAL.md`** (feature tour, demo accounts, run steps, evidence, bugs found, limits). Reset to the starting state: `./scripts/p2_reset.sh`. Tests: `node scripts/p2_e2e_a.cjs && node scripts/p2_e2e_b.cjs && node scripts/p2_e2e_c.cjs`.

## Honesty notes
- Run on a single 4 vCPU VM, loopback network, HTTP only. Performance figures are indicative, not guarantees.
- `probes_metabase.py`, `probes_superset.py` were run **inline** during the session and saved afterwards as transcriptions; they were **not re-executed in saved form**. The JSON in `evidence/` is from the original runs.
- `finalize_evidence.py` relabels a few rows (where my own test was wrong or a result is a gap/limitation rather than pass/fail). Every relabel carries a reason in its note.
- Nothing here touches real or customer data. Read `docs/SECURITY_CONFIGURATION.md` Part A before using any real system.

`portal/static/sdk.js` is a build of `@superset-ui/embedded-sdk` (Apache-2.0, © The Apache Software Foundation), included so you don't need Node to run the demo.
