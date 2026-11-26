// Identity-provider brute-force protection (Keycloak realm: 5 failures -> temporary lockout). Uses the spare account stranger.demo.
const { chromium } = require('playwright'); const L = require('./e2e_lib.cjs'); const rec = new L.Rec('p2_e2e_idp_lockout');
(async () => {
  const b = await chromium.launch(); const ctx = await b.newContext(); const page = await ctx.newPage(); const msgs = [];
  for (let i = 1; i <= 7; i++) { await page.goto(L.PORTAL + '/login'); await page.fill('#username', 'stranger.demo'); await page.fill('#password', 'wrong-' + i); await page.click('#kc-login'); await page.waitForTimeout(600);
    msgs.push((await page.innerText('body')).replace(/\s+/g, ' ').match(/(Invalid[^.]*\.|Account is[^.]*\.|temporarily[^.]*\.)/i)?.[0] || '(no message)'); }
  rec.r('TC-06', 'wrong passwords are rejected (7 attempts) and never create a session', !(await ctx.cookies()).some(c => c.name === 'if_sid'), msgs.join(' | '));
  await page.goto(L.PORTAL + '/login'); await page.fill('#username', 'stranger.demo'); await page.fill('#password', L.env.DEMO_PASSWORD); await page.click('#kc-login'); await page.waitForTimeout(1500);
  const t = (await page.innerText('body')).replace(/\s+/g, ' '); const blocked = !(await page.locator('#otp').count()) && !page.url().startsWith(L.PORTAL);
  rec.r('TC-06', 'after repeated failures even the CORRECT password is refused (account temporarily locked at the IdP)', blocked, t.slice(0, 160));
  await b.close(); rec.save();
})().catch(e => { console.error(e); process.exit(1); });
