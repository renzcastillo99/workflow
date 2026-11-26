// Phase 2 mini - browser test suite A: authentication, authorization, scoping, revocation, sessions, CSRF, theme, contrast, focus, mobile. SYNTHETIC data only.
const { chromium, request } = require('playwright'); const L = require('./e2e_lib.cjs'); const fs = require('fs'), path = require('path');
const SHOT = path.join(L.ROOT, 'evidence/screenshots'); fs.mkdirSync(SHOT, { recursive: true });
const rec = new L.Rec('p2_e2e_access'); const sleep = ms => new Promise(r => setTimeout(r, ms));
const pass = L.env.DEMO_PASSWORD; const cspMsgs = [];
(async () => {
  const browser = await chromium.launch();
  const mk = async (vp = { width: 1280, height: 900 }) => { const c = await browser.newContext({ viewport: vp, deviceScaleFactor: 1 }); const p = await c.newPage(); p.on('console', m => { if (/Content Security Policy|Refused to/.test(m.text())) cspMsgs.push(m.text().slice(0, 140)); }); return [c, p]; };
  const shot = (p, n) => p.screenshot({ path: path.join(SHOT, `p2_${n}.png`) });
  const jar = async (ctx) => (await ctx.storageState()).cookies.map(c => `${c.name}=${c.value}`).join('; ');
  const E = L.expected;
  // ---------- S1 anonymous ----------
  const anon = await request.newContext({ baseURL: L.PORTAL, maxRedirects: 0 });
  for (const [m, p, exp] of [['GET', '/', 303], ['GET', '/reports', 303], ['GET', '/reports/sales-live', 303], ['GET', '/admin/users', 303], ['GET', '/admin/audit', 303], ['GET', '/api/reports/sales-live/guest-token', 401], ['GET', '/docs', 404], ['GET', '/openapi.json', 404]]) {
    const r = await anon.fetch(p, { method: m }); rec.r('TC-06', `anonymous ${m} ${p} -> ${exp}`, r.status() === exp, r.status() + (r.headers().location ? ' -> ' + r.headers().location : ''));
  }
  let r = await anon.post('/admin/data/upload', { multipart: { csrf_token: 'x', file: { name: 'a.csv', mimeType: 'text/csv', buffer: Buffer.from('a') } } }); rec.r('TC-06', 'anonymous POST /admin/data/upload denied', [303, 401].includes(r.status()), r.status());
  r = await anon.get('/signin'); const h = r.headers();
  rec.r('TC-06', 'security headers present (CSP, nosniff, DENY, referrer, no-store)', !!h['content-security-policy'] && h['x-content-type-options'] === 'nosniff' && h['x-frame-options'] === 'DENY' && !!h['referrer-policy'] && h['cache-control'] === 'no-store', `csp=${(h['content-security-policy'] || '').slice(0, 70)}...`);
  rec.r('TC-06', "CSP has no 'unsafe-inline'/'unsafe-eval'", !/unsafe-/.test(h['content-security-policy'] || ''), h['content-security-policy']);
  // ---------- S2 IdP-level failures ----------
  { const [c, p] = await mk(); await p.goto(L.PORTAL + '/login'); await p.fill('#username', 'viewer.none'); await p.fill('#password', 'wrong-password'); await p.click('#kc-login'); await p.waitForTimeout(1500);
    const t = (await p.innerText('body')).replace(/\s+/g, ' '); rec.r('TC-06', 'IdP: wrong password rejected, no portal session', /invalid|incorrect/i.test(t) && !(await c.cookies()).some(k => k.name === 'if_sid'), t.slice(0, 120));
    await p.fill('#username', 'viewer.none'); await p.fill('#password', pass); await p.click('#kc-login'); await p.waitForSelector('#otp'); await p.fill('#otp', '000000'); await p.click('#kc-login'); await p.waitForTimeout(1500);
    const t2 = (await p.innerText('body')).replace(/\s+/g, ' '); rec.r('TC-06', 'IdP: correct password but WRONG TOTP code rejected (MFA enforced)', /invalid|incorrect/i.test(t2) && !(await c.cookies()).some(k => k.name === 'if_sid'), t2.slice(0, 120)); await c.close(); }
  // ---------- S3 stranger: authenticates at the IdP but is not provisioned ----------
  { const [c, p] = await mk(); await L.login(p, 'stranger.demo'); await p.waitForTimeout(1500);
    const ck = await c.cookies(); rec.r('TC-06', 'IdP-authenticated but NOT provisioned in portal -> denied, no session', p.url().includes('reason=denied') && !ck.some(k => k.name === 'if_sid'), p.url()); await shot(p, 'signin_denied'); await c.close(); }
  // ---------- S4 viewer.sales ----------
  const [cS, pS] = await mk(); await L.login(pS, 'viewer.sales'); await pS.waitForLoadState('networkidle');
  const ovS = await pS.innerText('body'); rec.r('FUNC-08', 'sales viewer overview lists ONLY assigned report', ovS.includes('Sales report (live data)') && !ovS.includes('Finance zero-revenue') && !ovS.includes('Large dataset'), ovS.replace(/\s+/g, ' ').slice(180, 330)); await shot(pS, 'overview_viewer');
  rec.r('FUNC-08', 'viewer sees no administration menu', !ovS.includes('Administration') && !ovS.includes('User management'), 'nav has no admin links');
  await pS.goto(L.PORTAL + '/reports'); const libS = await pS.innerText('body'); rec.r('FUNC-08', 'library lists only assigned report (no unauthorized titles)', libS.includes('Sales report (live data)') && !libS.includes('Finance') && !libS.includes('Large dataset'), 'ok'); await shot(pS, 'library');
  await pS.goto(L.PORTAL + '/reports/sales-live'); const t0 = Date.now(); const f1 = await L.frameHas(pS, E.v0.revenue_fmt);
  rec.r('TC-05', `embedded report (all branches) shows independent revenue ${E.v0.revenue_fmt}`, f1.ok, `${Date.now() - t0} ms; ${f1.text.slice(0, 110)}`); const fm = await L.frameHas(pS, '%'); rec.r('TC-05', 'margin KPI shown as a percentage (waits for the card to render)', /\d\d\.\d\d%/.test(fm.text), (fm.text.match(/\d\d\.\d\d%/) || ['none'])[0]);
  await pS.waitForTimeout(3000); await shot(pS, 'report_light');
  const bodyS = await pS.innerText('body'); rec.r('FUNC-11', 'report page shows "Last successful refresh" + scope', /Last successful refresh/.test(bodyS) && /Scope: all branches/.test(bodyS), (bodyS.match(/Last successful refresh:[^\n]*/) || [''])[0]);
  // theme: toggle, persist across reload & navigation, contrast
  const bg = () => pS.evaluate(() => getComputedStyle(document.body).backgroundColor);
  rec.r('TC-14', 'light theme canvas = #F1F5F9', (await bg()) === 'rgb(241, 245, 249)', await bg());
  await pS.goto(L.PORTAL + '/settings'); await pS.click('[data-theme-set="dark"]'); const bd = await bg(); rec.r('TC-14', 'dark theme canvas = #0F172A', bd === 'rgb(15, 23, 42)', bd);
  await pS.reload(); rec.r('TC-14', 'dark preference persists after reload', (await bg()) === 'rgb(15, 23, 42)', await bg());
  await pS.goto(L.PORTAL + '/'); rec.r('TC-14', 'dark preference persists across pages', (await bg()) === 'rgb(15, 23, 42)', await bg()); await shot(pS, 'overview_dark');
  await pS.goto(L.PORTAL + '/reports/sales-live'); await L.frameHas(pS, E.v0.revenue_fmt); await pS.waitForTimeout(2500); await shot(pS, 'report_dark');
  for (const theme of ['light', 'dark']) {
    await pS.evaluate(t => document.documentElement.setAttribute('data-theme', t), theme);
    const v = await pS.evaluate(() => { const g = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim(); return Object.fromEntries(['--text', '--muted', '--surface', '--canvas', '--primary', '--on-primary', '--success', '--warning', '--error', '--nav', '--nav-text', '--nav-muted'].map(k => [k, g(k)])); });
    const pairs = [['text/surface', v['--text'], v['--surface']], ['muted/surface', v['--muted'], v['--surface']], ['text/canvas', v['--text'], v['--canvas']], ['button text/primary', v['--on-primary'], v['--primary']], ['link primary/surface', v['--primary'], v['--surface']], ['success/surface', v['--success'], v['--surface']], ['warning/surface', v['--warning'], v['--surface']], ['error/surface', v['--error'], v['--surface']], ['nav text/nav', v['--nav-text'], v['--nav']], ['nav muted/nav', v['--nav-muted'], v['--nav']]];
    for (const [n, a, b] of pairs) { const cr = L.contrast(a, b); rec.r('TC-14', `contrast ${theme}: ${n} >= 4.5:1`, cr >= 4.5, cr.toFixed(2), `${a} on ${b}`); }
  }
  await pS.evaluate(() => document.documentElement.setAttribute('data-theme', 'light')); await pS.evaluate(() => localStorage.setItem('if-theme', 'light'));
  // unassigned access (direct URL + API), identical answer for non-existent
  const resp = await pS.goto(L.PORTAL + '/reports/finance-check'); const body403 = await pS.innerText('body');
  rec.r('FUNC-08', 'direct URL to UNASSIGNED report -> 403 Permission denied page', resp.status() === 403 && /Permission denied/.test(body403) && !body403.includes('Finance zero-revenue'), `${resp.status()} ${body403.replace(/\s+/g, ' ').slice(0, 90)}`); await shot(pS, 'permission_denied');
  const ghost = await pS.goto(L.PORTAL + '/reports/does-not-exist'); const bodyGhost = await pS.innerText('body'); rec.r('FUNC-08', 'NON-EXISTENT report gives the same 403 (no existence leak)', ghost.status() === 403 && bodyGhost === body403, ghost.status());
  const tokOf = async (rid) => pS.evaluate(async rid => { const r = await fetch('/api/reports/' + rid + '/guest-token', { credentials: 'same-origin' }); let b = null; try { b = await r.json(); } catch (e) {} return { s: r.status, b }; }, rid);
  let a = await tokOf('finance-check'); rec.r('FUNC-08', 'API guest-token for UNASSIGNED report -> 403, no token', a.s === 403 && !(a.b && a.b.token), `${a.s} ${JSON.stringify(a.b)}`);
  a = await tokOf('large-1m'); rec.r('FUNC-08', 'API guest-token for another unassigned report -> 403', a.s === 403, a.s);
  const xs = await request.newContext({ baseURL: L.PORTAL, maxRedirects: 0, extraHTTPHeaders: { Cookie: await jar(cS), 'Sec-Fetch-Site': 'cross-site' } }); r = await xs.get('/api/reports/sales-live/guest-token'); rec.r('TC-07', 'cross-site request for a guest token refused even for an ASSIGNED report', r.status() === 403, r.status());
  for (const p of ['/admin/users', '/admin/audit', '/admin/data', '/admin/refresh']) { const rr = await pS.goto(L.PORTAL + p); rec.r('FUNC-13', `viewer blocked from ${p}`, rr.status() === 403, rr.status()); }
  const salesSid = (await cS.cookies()).find(k => k.name === 'if_sid');
  const salesTok = (await tokOf('sales-live')).b.token;      // keep a live guest token to demonstrate the revocation window later
  // ---------- S5 viewer.makati: row scope ----------
  const [cM, pM] = await mk(); await L.login(pM, 'viewer.makati'); await pM.goto(L.PORTAL + '/reports/sales-live'); const fM = await L.frameHas(pM, E.v0.makati_revenue_fmt);
  rec.r('TC-07', `Makati-scoped viewer sees ONLY Makati revenue ${E.v0.makati_revenue_fmt}`, fM.ok && !fM.text.includes(E.v0.revenue_fmt), fM.text.slice(0, 100)); await pM.waitForTimeout(2500); await shot(pM, 'report_makati_scoped');
  rec.r('TC-07', 'scope badge shown to the viewer', /Scope: Makati/.test(await pM.innerText('body')), 'Scope: Makati');
  const mTok = (await pM.evaluate(async () => (await (await fetch('/api/reports/sales-live/guest-token')).json()).token));
  const ss = (tok, body) => fetch('http://127.0.0.1:8088/api/v1/chart/data', { method: 'POST', headers: { 'Content-Type': 'application/json', 'X-GuestToken': tok }, body: JSON.stringify(body) });
  const q = (ds, dash, filters = []) => ({ datasource: { id: ds, type: 'table' }, form_data: { dashboardId: dash }, force: true, result_format: 'json', result_type: 'full', queries: [{ metrics: ['revenue'], columns: [], filters, row_limit: 10, extras: {} }] });
  const lv = L.state['sales-live']; let sr = await ss(mTok, q(lv.dataset_id, lv.dashboard_id)); let js = await sr.json(); const rv = js.result && js.result[0].data[0].revenue;
  rec.r('TC-07', 'token-level: Makati token queried DIRECTLY at Superset returns only Makati total', sr.status === 200 && Number(rv).toFixed(2) === E.v0.Makati.revenue, `${sr.status} revenue=${rv}`);
  sr = await ss(mTok, q(lv.dataset_id, lv.dashboard_id, [{ col: 'branch', op: 'IN', val: ['Cebu'] }])); js = await sr.json(); rec.r('TC-07', 'token-level: Makati token + filter branch=Cebu -> no Cebu data (bypass attempt)', sr.status === 200 && js.result[0].data[0].revenue === null, `${sr.status} ${JSON.stringify(js.result && js.result[0].data)}`);
  const fz = L.state['finance-check']; sr = await ss(mTok, q(fz.dataset_id, lv.dashboard_id)); rec.r('TC-16', "token-level: Makati token cannot read another report's dataset", sr.status === 403, sr.status);
  sr = await fetch('http://127.0.0.1:8088/api/v1/dashboard/', { headers: { 'X-GuestToken': mTok } }); const dl = sr.status === 200 ? (await sr.json()).result.map(d => d.dashboard_title) : []; rec.r('TC-07', 'token-level: guest cannot list other dashboards', dl.every(t => /live/.test(t)), JSON.stringify(dl));
  for (const p of ['/api/v1/security/users/', '/api/v1/database/', '/api/v1/sqllab/execute/']) { sr = await fetch('http://127.0.0.1:8088' + p, { method: p.includes('sqllab') ? 'POST' : 'GET', headers: { 'X-GuestToken': mTok, 'Content-Type': 'application/json' }, body: p.includes('sqllab') ? JSON.stringify({ database_id: 1, sql: 'select 1' }) : undefined }); rec.r('TC-07', `token-level: guest token on ${p} denied`, [401, 403].includes(sr.status), sr.status, sr.status === 400 ? 'CSRF 400 masks the authz decision; covered by the guest-role permission inspection (Phase 1)' : '', sr.status === 400 ? 'INCONCLUSIVE' : null); }
  // ---------- S6 viewer.none ----------
  const [cN, pN] = await mk(); await L.login(pN, 'viewer.none'); await pN.waitForLoadState('networkidle'); const tn = await pN.innerText('body');
  rec.r('FUNC-08', 'provisioned viewer with NO assignment: empty state, default-deny', /No reports assigned yet/.test(tn), tn.replace(/\s+/g, ' ').slice(180, 300)); await shot(pN, 'empty_state');
  const rn = await pN.goto(L.PORTAL + '/reports/sales-live'); rec.r('FUNC-08', 'unassigned viewer direct URL -> 403', rn.status() === 403, rn.status()); await cN.close();
  // ---------- S7 admin ----------
  const [cA, pA] = await mk(); await L.login(pA, 'admin.demo'); await pA.waitForLoadState('networkidle'); const oa = await pA.innerText('body');
  rec.r('UI-02', 'admin overview shows operational summary', /Operational summary/.test(oa) && /Active users/.test(oa) && /Denied events/.test(oa), oa.replace(/\s+/g, ' ').slice(170, 330)); await shot(pA, 'overview_admin');
  const adminSid = (await cA.cookies()).find(k => k.name === 'if_sid');
  await pA.goto(L.PORTAL + '/admin/users'); await shot(pA, 'users'); const ut = await pA.innerText('body'); rec.r('UI-07', 'user management lists users, roles and per-report scope', /Sam Sales/.test(ut) && /Makati/.test(ut) && /Mia Makati/.test(ut), 'ok');
  const adm = await request.newContext({ baseURL: L.PORTAL, maxRedirects: 0, extraHTTPHeaders: { Cookie: await jar(cA) } });
  r = await adm.post('/admin/users/2/active', { form: { active: '0' } }); rec.r('TC-07', 'CSRF: admin POST without form token -> rejected', r.status() === 403, r.status());
  r = await adm.post('/admin/users/2/active', { form: { active: '0', csrf_token: 'forged-token' } }); rec.r('TC-07', 'CSRF: admin POST with forged token -> rejected', r.status() === 403, r.status());
  const sales = L.py("import db;print(db.one(\"select id from users where email='viewer.sales@feasibility.invalid'\")['id'])");
  // revocation of an assignment (UI): makati loses large-1m immediately
  let mr = await pM.goto(L.PORTAL + '/reports/large-1m'); rec.r('FUNC-12', 'before revoke: Makati viewer opens Large dataset', mr.status() === 200, mr.status());
  pA.on('dialog', d => d.accept()); await pA.goto(L.PORTAL + '/admin/users');
  const makRow = pA.locator('tr', { hasText: 'Mia Makati' }); const t1 = Date.now(); await makRow.locator('form:has(input[value="large-1m"]) button:has-text("Revoke")').click(); await pA.waitForLoadState('networkidle');
  mr = await pM.goto(L.PORTAL + '/reports/large-1m'); rec.r('FUNC-12', `after revoke: SAME live session now denied (${Date.now() - t1} ms)`, mr.status() === 403, mr.status()); await shot(pA, 'users_after_revoke');
  const libM = await (async () => { await pM.goto(L.PORTAL + '/reports'); return pM.innerText('body'); })(); rec.r('FUNC-12', 'revoked report disappears from library', !libM.includes('Large dataset'), 'ok');
  await makRow.locator('select[name="report_id"]').selectOption('large-1m'); await makRow.locator('select[name="scope"]').selectOption('Makati'); await makRow.locator('button:has-text("Assign")').click(); await pA.waitForLoadState('networkidle');
  mr = await pM.goto(L.PORTAL + '/reports/large-1m'); rec.r('FUNC-12', 'assign via UI restores access (scope Makati)', mr.status() === 200, mr.status());
  // deactivate user: sessions end immediately; guest token already issued lives <= 5 min (documented window)
  await pA.goto(L.PORTAL + '/admin/users'); const salesRow = pA.locator('tr', { hasText: 'Sam Sales' }); const t2 = Date.now(); await salesRow.locator('button:has-text("Deactivate")').click(); await pA.waitForLoadState('networkidle');
  const sr1 = await pS.goto(L.PORTAL + '/reports'); rec.r('TC-11', `deactivated user's live session ended immediately (${Date.now() - t2} ms)`, pS.url().includes('/signin'), pS.url());
  const replay = await request.newContext({ baseURL: L.PORTAL, maxRedirects: 0, extraHTTPHeaders: { Cookie: `if_sid=${salesSid.value}` } }); r = await replay.get('/reports'); rec.r('TC-11', 'replaying the deactivated user\'s old session cookie -> rejected', r.status() === 303, r.status());
  const [cS2, pS2] = await mk(); await L.login(pS2, 'viewer.sales'); await pS2.waitForTimeout(1500); rec.r('TC-11', 'deactivated user cannot sign in again (IdP ok, portal denies)', pS2.url().includes('reason=denied'), pS2.url()); await cS2.close();
  sr = await ss(salesTok, q(lv.dataset_id, lv.dashboard_id)); rec.r('TC-11', 'KNOWN WINDOW: an already-issued guest token still works until its 5-minute expiry', sr.status === 200, `HTTP ${sr.status}`, 'revocation window = guest-token TTL (300 s); keep short', 'INFO');
  await pA.goto(L.PORTAL + '/admin/users'); await pA.locator('tr', { hasText: 'Sam Sales' }).locator('button:has-text("Re-activate")').click(); await pA.waitForLoadState('networkidle');
  const [cS3, pS3] = await mk(); await L.login(pS3, 'viewer.sales'); await pS3.waitForLoadState('networkidle'); rec.r('TC-11', 're-activated user can sign in again', !pS3.url().includes('denied') && /Sales report/.test(await pS3.innerText('body')), pS3.url());
  // add-user flow
  await pA.goto(L.PORTAL + '/admin/users'); await pA.fill('#n', 'Pat Pilot'); await pA.fill('#e', 'pat.pilot@feasibility.invalid'); await pA.click('button:has-text("Add user")'); await pA.waitForLoadState('networkidle'); rec.r('FUNC-12', 'admin adds a user (sees nothing until assigned)', /Pat Pilot/.test(await pA.innerText('body')), 'added');
  // ---------- S8 sessions ----------
  const idleSid = (await cS3.cookies()).find(k => k.name === 'if_sid').value;
  L.py(`import db,datetime as d;db.run("update sessions set last_seen=? where sid=?",(d.datetime.now(d.timezone.utc)-d.timedelta(hours=3)).isoformat(timespec='seconds'),'${idleSid}')`);
  await pS3.goto(L.PORTAL + '/reports'); rec.r('TC-06', 'idle session (3 h inactive; limit 30 min) rejected server-side', pS3.url().includes('/signin'), pS3.url());
  const [cS4, pS4] = await mk(); await L.login(pS4, 'viewer.sales'); await pS4.waitForLoadState('networkidle'); const sid4 = (await cS4.cookies()).find(k => k.name === 'if_sid').value;
  await pS4.goto(L.PORTAL + '/settings'); await shot(pS4, 'settings'); await pS4.click('button:has-text("Sign out")'); await pS4.waitForLoadState('networkidle'); rec.r('TC-06', 'sign out ends the session and returns to sign-in', /signin/.test(pS4.url()) && !(await cS4.cookies()).some(k => k.name === 'if_sid'), pS4.url());
  const rp = await request.newContext({ baseURL: L.PORTAL, maxRedirects: 0, extraHTTPHeaders: { Cookie: `if_sid=${sid4}` } }); r = await rp.get('/reports'); rec.r('TC-06', 'old cookie after sign-out is useless (server-side session deleted)', r.status() === 303, r.status());
  // ---------- S9 keyboard / focus ----------
  const [cK, pK] = await mk(); await L.login(pK, 'viewer.sales'); await pK.waitForLoadState('networkidle'); await pK.goto(L.PORTAL + '/'); await pK.evaluate(() => document.activeElement && document.activeElement.blur());
  const stops = []; for (let i = 0; i < 14; i++) { await pK.keyboard.press('Tab'); const s = await pK.evaluate(() => { const e = document.activeElement; const cs = getComputedStyle(e); return { t: (e.textContent || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 26), ow: parseFloat(cs.outlineWidth), os: cs.outlineStyle, lx: e.getBoundingClientRect().left, body: e === document.body }; }); if (s.body) break; stops.push(s); }
  rec.r('TC-15', 'first Tab stop is the "Skip to content" link, and it becomes visible', stops[0].t.startsWith('Skip') && stops[0].lx >= 0, JSON.stringify(stops[0]));
  const bad = stops.filter(s => !(s.os !== 'none' && s.ow >= 2)); rec.r('TC-15', `every keyboard stop (${stops.length}) has a visible focus ring (>=2px) and there are enough stops`, bad.length === 0 && stops.length >= 8, `stops: ${stops.map(s => s.t).join(' | ')}`);
  await cK.close();
  // ---------- S10 mobile ----------
  const [cMo, pMo] = await mk({ width: 390, height: 844 }); await L.login(pMo, 'viewer.sales'); await pMo.waitForLoadState('networkidle');
  for (const p of ['/', '/reports', '/settings']) { await pMo.goto(L.PORTAL + p); const hs = await pMo.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth); rec.r('TC-15', `mobile 390px: no horizontal scroll on ${p}`, !hs, hs ? 'scrolls' : 'fits'); }
  await pMo.goto(L.PORTAL + '/'); await shot(pMo, 'mobile_overview'); await pMo.click('#navtoggle-m'); const open = await pMo.evaluate(() => document.getElementById('sidebar').classList.contains('open')); rec.r('TC-15', 'mobile: menu button opens the navigation', open, open); await shot(pMo, 'mobile_menu_open');
  await pMo.click('#navclose'); const closed = await pMo.evaluate(() => !document.getElementById('sidebar').classList.contains('open')); rec.r('TC-15', 'mobile: the open menu can be closed (Close menu button)', closed, closed); await pMo.click('#navtoggle-m'); await pMo.keyboard.press('Escape'); const esc = await pMo.evaluate(() => !document.getElementById('sidebar').classList.contains('open')); rec.r('TC-15', 'mobile: Escape closes the menu (keyboard)', esc, esc); await pMo.goto(L.PORTAL + '/reports/sales-live'); const fMo = await L.frameHas(pMo, E.v0.revenue_fmt); await pMo.waitForTimeout(2500); await shot(pMo, 'mobile_report'); const hsr = await pMo.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth);
  rec.r('TC-15', 'mobile: report page fits width (page-level)', !hsr, hsr ? 'scrolls' : 'fits'); rec.r('TC-15', 'mobile: embedded Superset layout usable? (visual check required)', true, 'Phase 1 found Superset grid squeezed at 390px: see screenshot p2_mobile_report.png', 'known limitation: needs a single-column dashboard layout', 'INFO'); await cMo.close();
  const [cMa, pMa] = await mk({ width: 390, height: 844 }); await L.login(pMa, 'admin.demo'); await pMa.waitForLoadState('networkidle');
  for (const p of ['/admin/users', '/admin/audit', '/admin/data', '/admin/refresh']) { await pMa.goto(L.PORTAL + p); const hs = await pMa.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth); rec.r('TC-15', `mobile 390px admin: no page-level horizontal scroll on ${p}`, !hs, hs ? 'scrolls' : 'fits (tables scroll inside their own wrapper)'); } await shot(pMa, 'mobile_admin_users'); await cMa.close();
  rec.r('TC-07', 'no CSP violations reported in the browser console across all pages', cspMsgs.length === 0, cspMsgs.slice(0, 3).join(' || ') || 'none');
  await browser.close(); rec.save();
})().catch(e => { console.error('SUITE ERROR', e); process.exit(1); });
