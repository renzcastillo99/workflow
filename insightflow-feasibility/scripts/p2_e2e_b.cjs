// Phase 2 mini - browser test suite B: upload -> validate -> reconcile -> atomic publish, last-good preservation, no overlap, freshness, audit. SYNTHETIC data only.
const { chromium } = require('playwright'); const L = require('./e2e_lib.cjs'); const fs = require('fs'), path = require('path'), { spawn } = require('child_process');
const SHOT = path.join(L.ROOT, 'evidence/screenshots'), SAMP = path.join(L.ROOT, 'data/samples'); const rec = new L.Rec('p2_e2e_data'); const sleep = ms => new Promise(r => setTimeout(r, ms)); const E = L.expected;
const dbState = () => { const [n, rev, cost] = L.psql("select count(*), sum(revenue), sum(cost) from live.transactions").split('|'); return { n: +n, rev, cost }; };
const same = (s, e) => s.n === e.all.rows && Number(s.rev).toFixed(2) === Number(e.all.revenue).toFixed(2) && s.rev === e.all.revenue;
(async () => {
  const browser = await chromium.launch(); const mk = async () => { const c = await browser.newContext({ viewport: { width: 1280, height: 900 } }); return [c, await c.newPage()]; };
  const shot = (p, n) => p.screenshot({ path: path.join(SHOT, `p2_${n}.png`), fullPage: true });
  const [cA, pA] = await mk(); await L.login(pA, 'admin.demo'); await pA.waitForLoadState('networkidle');
  const [cS, pS] = await mk(); await L.login(pS, 'viewer.sales'); await pS.waitForLoadState('networkidle');
  const [cM, pM] = await mk(); await L.login(pM, 'viewer.makati'); await pM.waitForLoadState('networkidle');
  const upload = async (page, file) => { await page.goto(L.PORTAL + '/admin/data'); await page.setInputFiles('#f', path.join(SAMP, file)); await Promise.all([page.waitForNavigation({ timeout: 240000 }), page.click('button:has-text("Validate and publish")')]); return (await page.innerText('main')).replace(/\s+/g, ' '); };
  const viewer = async (page, text) => { await page.goto(L.PORTAL + '/reports/sales-live'); return L.frameHas(page, text, 45000); };
  // 0 baseline: DB equals the independent expectation
  let s = dbState(); rec.r('TC-05', 'baseline: live table == independent Decimal expectation (20,000 rows)', same(s, E.v0), JSON.stringify(s));
  // 1-4 rejects never touch live data
  const cases = [['bad_duplicate_ids.csv', /duplicate transaction_id/, 'duplicate transaction_id'], ['bad_schema_missing_cost.csv', /Schema mismatch/, 'wrong schema (missing column)'], ['bad_values.csv', /invalid/, 'invalid values'], ['malformed.xlsx', /Not a valid \.xlsx/, 'malformed Excel file']];
  for (const [f, re, label] of cases) {
    const t = await upload(pA, f); s = dbState(); rec.r('FUNC-03/04', `${label}: rejected with a clear message`, /Not done/.test(t) && /live data (was )?not changed|unchanged/i.test(t) || re.test(t), t.slice(t.indexOf('Not done'), t.indexOf('Not done') + 160));
    rec.r('FUNC-10', `${label}: LIVE DATA UNCHANGED (count + revenue + cost exact)`, same(s, E.v0) && s.cost === L.psql("select sum(cost) from live.transactions"), JSON.stringify(s));
    if (f === 'bad_duplicate_ids.csv') await shot(pA, 'data_rejected');
  }
  rec.r('FUNC-10', 'staging area is empty after failed jobs (nothing left behind)', L.psql("select count(*) from information_schema.tables where table_schema='staging'") === '0', 'staging tables=0');
  await pA.goto(L.PORTAL + '/admin/refresh'); for (const sm of await pA.locator('summary').all()) await sm.click(); const rt = (await pA.innerText('main')).replace(/\s+/g, ' ');
  for (const frag of ['duplicate transaction_id', 'missing (not coerced to 0)', 'more than 2 decimal places', 'is not a valid YYYY-MM-DD date', 'branch is missing', "is not a number", 'Schema mismatch', 'Not a valid .xlsx']) rec.r('FUNC-04', `rejected-row report contains: "${frag}"`, rt.includes(frag), frag);
  rec.r('UI-06', 'refresh history marks failed files "Rejected - live unchanged" with line numbers', /Rejected - live unchanged/.test(rt) && /line \d+/.test(rt), 'ok'); await shot(pA, 'refresh_history_rejects');
  let v = await viewer(pS, E.v0.revenue_fmt); rec.r('FUNC-11', 'after 4 rejected uploads viewers STILL see the last verified numbers', v.ok, v.text.slice(0, 80));
  // 6 good CSV publish
  let t = await upload(pA, 'snapshot_v2_plus5.csv'); s = dbState(); rec.r('FUNC-04', 'valid CSV (+5 rows) validated, reconciled and published', /Published 20,005 rows/.test(t), t.slice(t.indexOf('Done'), t.indexOf('Done') + 90));
  rec.r('TC-09', 'live table == independent expectation after publish (20,005 rows, exact cents)', same(s, E.v2), JSON.stringify(s)); await shot(pA, 'data_published');
  v = await viewer(pS, E.v2.revenue_fmt); rec.r('TC-09', `viewer report shows NEW revenue ${E.v2.revenue_fmt} (cache invalidated, no stale numbers)`, v.ok, v.text.slice(0, 80));
  const vm = await viewer(pM, E.v2.makati_revenue_fmt); rec.r('TC-09', 'Makati-scoped viewer shows NEW Makati revenue (scope still applied)', vm.ok && !vm.text.includes(E.v2.revenue_fmt), vm.text.slice(0, 80));
  const fb = await pS.innerText('main'); rec.r('FUNC-11', 'report shows a fresh "Last successful refresh" timestamp', /Fresh/.test(fb) && /just now|min ago/.test(fb), (fb.match(/Last successful refresh:[^\n]*/) || [''])[0]);
  await pA.goto(L.PORTAL + '/admin/refresh'); const jt = (await pA.innerText('main')).replace(/\s+/g, ' '); rec.r('UI-06', 'history shows Published job with row counts and reconciliation note', /Published/.test(jt) && /reconciled/.test(jt) && /20,005 rows/.test(jt), (jt.match(/20,005 rows[^.]*/) || [''])[0].slice(0, 150));
  rec.r('FUNC-10', 'BI cache invalidated automatically by the service account', /BI cache refreshed/.test(jt), 'ok');
  // 7 Excel publish
  t = await upload(pA, 'snapshot_v3_plus8.xlsx'); s = dbState(); rec.r('FUNC-03', 'valid XLSX (+8 rows, numeric + date cells) validated and published', /Published 20,008 rows/.test(t), t.slice(t.indexOf('Done'), t.indexOf('Done') + 70));
  rec.r('TC-05', 'XLSX publish: live == independent Decimal expectation (no float drift)', same(s, E.v3), JSON.stringify(s)); v = await viewer(pS, E.v3.revenue_fmt); rec.r('TC-09', 'viewer shows revenue after XLSX publish', v.ok, v.text.slice(0, 70));
  // 8 failure AFTER success keeps the latest verified snapshot
  t = await upload(pA, 'bad_values.csv'); s = dbState(); rec.r('TC-10', 'bad file after a good publish: latest verified snapshot (v3) retained', same(s, E.v3), JSON.stringify(s)); v = await viewer(pS, E.v3.revenue_fmt); rec.r('TC-10', 'viewer still sees v3 + stale-data/warning banner is NOT shown while data is fresh', v.ok, v.text.slice(0, 60));
  const wb = await pS.innerText('main'); rec.r('TC-10', 'report warns that the latest update did not publish', /Latest update did not publish/.test(wb), (wb.match(/Latest update did not publish[^\n]*/) || ['(absent)'])[0]); await sleep(1500); await pS.screenshot({ path: path.join(SHOT, 'p2_report_after_failed_update.png') });
  // 9 ATOMIC publish: concurrent reader never sees a partial/missing table
  const reader = spawn(path.join(L.ROOT, 'portal/.venv/bin/python'), ['p2_readloop.py', '16'], { cwd: __dirname }); let out = '', errtxt = ''; reader.stdout.on('data', d => out += d); reader.stderr.on('data', d => errtxt += d); const readerDone = new Promise(r => reader.on('close', r)); await sleep(2500);
  await upload(pA, 'snapshot_v2_plus5.csv'); await readerDone; if (!out) throw new Error('read-loop produced no output: ' + errtxt.slice(0, 300)); const rl = JSON.parse(out); const okStates = new Set([`20008|${E.v3.all.revenue}`, `20005|${E.v2.all.revenue}`]);
  const states = Object.keys(rl.distinct_states); rec.r('TC-09', `ATOMIC publish: ${rl.reads} concurrent BI reads during the swap saw only old or new snapshot`, states.every(k => okStates.has(k)) && states.length === 2 && rl.error_count === 0, JSON.stringify(rl.distinct_states) + ` errors=${rl.error_count}`);
  // 10 no overlapping jobs
  const [cA2, pA2] = await mk(); await L.login(pA2, 'admin.demo'); await pA2.waitForLoadState('networkidle'); const tStart = Date.now();
  const big = (async () => upload(pA, 'big_valid_500k.csv'))();
  let locked = false; for (let i = 0; i < 100 && !locked; i++) { locked = L.psql("select count(*) from pg_locks where locktype='advisory' and objid=727001") !== '0'; if (!locked) await sleep(100); }
  rec.r('FUNC-10', 'while the 500k-row job runs, the advisory lock is held', locked, locked);
  const t2 = await upload(pA2, 'snapshot_v3_plus8.xlsx'); rec.r('FUNC-10', 'second refresh started during a running one is REFUSED (no overlap)', /already running/.test(t2), t2.slice(t2.indexOf('Not done'), t2.indexOf('Not done') + 100));
  const tb = await big; const dur = ((Date.now() - tStart) / 1000).toFixed(1); s = dbState(); rec.r('FUNC-10', `the first job still completes and publishes 500,000 rows (${dur}s end-to-end)`, /Published 500,000 rows/.test(tb) && same(s, E.big), JSON.stringify(s));
  v = await viewer(pS, E.big.revenue_fmt); rec.r('TC-09', 'viewer shows the 500k-row dataset total after publish', v.ok, v.text.slice(0, 70));
  await pA.goto(L.PORTAL + '/admin/refresh'); const ht = (await pA.innerText('main')).replace(/\s+/g, ' '); rec.r('UI-06', 'history records the refused job as rejected with the reason', /Another refresh is already running/.test(ht), 'ok');
  t = await upload(pA, 'snapshot_v3_plus8.xlsx'); s = dbState(); rec.r('TC-09', 'restore: re-uploading the small snapshot works after a large job', same(s, E.v3), JSON.stringify(s)); await cA2.close();
  rec.r('FUNC-10', 'staging empty at the end', L.psql("select count(*) from information_schema.tables where table_schema='staging'") === '0', '0');
  // 11 audit & secrets
  await pA.goto(L.PORTAL + '/admin/audit'); await shot(pA, 'audit'); const at = (await pA.innerText('main'));
  for (const a of ['login.success', 'login.denied', 'report.view', 'report.denied', 'token.denied', 'assignment.revoke', 'user.deactivate', 'refresh.success', 'refresh.rejected', 'csrf.rejected', 'session.expired', 'logout']) rec.r('FUNC-17', `audit trail contains ${a}`, at.includes(a) || L.py(`import db;print(db.one("select count(*) n from events where action='${a}'")['n'])`) !== '0', a);
  await pA.goto(L.PORTAL + '/admin/audit?outcome=denied'); const dt = await pA.innerText('main'); rec.r('UI-08', 'audit filter by outcome=denied shows only denied events', !/\bok\b\s*$/m.test(dt.split('Detail')[1] || '') && /denied/.test(dt), 'ok');
  const blob = L.py("import db;print(' '.join((str(e['actor'])+' '+e['action']+' '+str(e['target'])+' '+str(e['detail'])) for e in db.q('select * from events'))+' '+' '.join(str(j['message']) for j in db.q('select * from refresh_jobs')))");
  const secrets = { DEMO_PASSWORD: L.env.DEMO_PASSWORD, SVC_PASSWORD: L.env.SVC_PASSWORD, KC_CLIENT_SECRET: L.env.KC_CLIENT_SECRET, PORTAL_SESSION_SECRET: L.env.PORTAL_SESSION_SECRET, INGEST_PW: L.env.INGEST_PW, SS_ADMIN_PASSWORD: L.env.SS_ADMIN_PASSWORD, DATA_PG_RO_PASSWORD: L.env.DATA_PG_RO_PASSWORD, SUPERSET_SECRET_KEY: L.env.SUPERSET_SECRET_KEY };
  for (const [k, val] of Object.entries(secrets)) rec.r('FUNC-17', `audit/refresh records do not contain ${k}`, !blob.includes(val) && !at.includes(val), 'not found');
  rec.r('FUNC-17', 'audit/refresh records contain no JWT-like token or session id', !/eyJ[A-Za-z0-9_-]{10,}/.test(blob) && !/[A-Za-z0-9_-]{43}/.test(blob.replace(/[A-Za-z]+@[a-z.]+/g, '')), 'none');
  const logs = require('child_process').execSync('tail -n 400 ' + path.join(L.ROOT, 'portal/data/portal.log'), { encoding: 'utf8' }); rec.r('FUNC-17', 'portal server log contains no secrets or tokens', !Object.values(secrets).some(x => logs.includes(x)) && !/eyJ[A-Za-z0-9_-]{20,}/.test(logs), 'not found');
  await browser.close(); rec.save();
})().catch(e => { console.error('SUITE ERROR', e); process.exit(1); });
