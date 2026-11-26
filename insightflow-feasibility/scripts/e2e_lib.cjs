// Shared helpers for the Phase 2 browser tests (Playwright). Secrets are read from the gitignored files at runtime.
const crypto = require('crypto'), fs = require('fs'), path = require('path');
const ROOT = path.resolve(__dirname, '..');
const env = Object.fromEntries(fs.readFileSync(path.join(ROOT, '.env'), 'utf8').split('\n').filter(l => l.includes('=') && !l.startsWith('#')).map(l => [l.slice(0, l.indexOf('=')), l.slice(l.indexOf('=') + 1)]));
const RAW = JSON.parse(fs.readFileSync(path.join(ROOT, 'docker/keycloak/.totp_raw.json'), 'utf8'));
const PORTAL = 'http://127.0.0.1:9000';
const used = {};
async function freshCode(user) {   // Keycloak rejects a TOTP code that was already used -> pick an unused 30 s step (current, next, previous)
  for (;;) { const cur = Math.floor(Date.now() / 1000 / 30); used[user] = used[user] || new Set();
    for (const o of [0, 1, -1]) if (!used[user].has(cur + o)) { used[user].add(cur + o); return totp(user, o); }
    await new Promise(r => setTimeout(r, 31000 - (Date.now() % 30000))); } }
function totp(user, offset = 0) {   // RFC 6238, HMAC-SHA1, 30 s, 6 digits; key = the raw secret string Keycloak stored
  const step = Math.floor(Date.now() / 1000 / 30) + offset, buf = Buffer.alloc(8); buf.writeBigUInt64BE(BigInt(step));
  const h = crypto.createHmac('sha1', Buffer.from(RAW[user])).update(buf).digest(), o = h[19] & 0xf;
  return String(((h[o] & 0x7f) << 24 | h[o + 1] << 16 | h[o + 2] << 8 | h[o + 3]) % 1000000).padStart(6, '0');
}
async function login(page, short, { password = env.DEMO_PASSWORD, otp = true } = {}) {
  await page.goto(PORTAL + '/login', { waitUntil: 'domcontentloaded' });
  await page.fill('#username', short); await page.fill('#password', password); await page.click('#kc-login');
  if (!otp) return;
  for (let attempt = 0; attempt < 4; attempt++) {                 // Keycloak rejects a TOTP code used in the last ~minute (also by earlier processes): retry on a fresh 30 s window
    await page.waitForSelector('#otp', { timeout: 15000 }); await page.fill('#otp', await freshCode(short)); await page.click('#kc-login');
    try { await page.waitForURL(u => u.toString().startsWith(PORTAL), { timeout: 8000 }); return; } catch (e) {}
    await new Promise(r => setTimeout(r, 31000 - (Date.now() % 30000)));       // wait for the next TOTP step, then try a new code
  }
  throw new Error('login did not complete for ' + short + ' (still at ' + page.url() + ')');
}
module.exports = { env, PORTAL, totp, freshCode, login, ROOT };
// ---- evidence recorder + small utilities ----
const { execSync } = require('child_process');
class Rec {
  constructor(name) { this.name = name; this.rows = []; }
  r(tc, check, pass, observed, note = '', status = null) {
    const row = { tc, check, status: status || (pass ? 'PASS' : 'FAIL'), observed: String(observed).slice(0, 300), note, ts: new Date().toISOString().slice(0, 19) + 'Z' };
    this.rows.push(row); console.log(`[${row.status}] ${tc} ${check} | ${row.observed.slice(0, 140)}`);
  }
  save() { fs.writeFileSync(path.join(ROOT, 'evidence', this.name + '.json'), JSON.stringify(this.rows, null, 2)); const p = this.rows.filter(x => x.status === 'PASS').length, f = this.rows.filter(x => x.status === 'FAIL').length;
    console.log(`\n${this.name}: ${p} PASS, ${f} FAIL, ${this.rows.length - p - f} other of ${this.rows.length} -> evidence/${this.name}.json`); }
}
const psql = (sql) => execSync(`docker exec -i if-data-pg psql -U insightflow_admin -d clientdata -At -F '|' -c "${sql.replace(/"/g, '\\"')}"`, { encoding: 'utf8' }).trim();
const py = (code) => execSync(`${path.join(ROOT, 'portal/.venv/bin/python')} -c ${JSON.stringify(code)}`, { cwd: path.join(ROOT, 'portal'), encoding: 'utf8' }).trim();
const expected = JSON.parse(fs.readFileSync(path.join(ROOT, 'evidence/p2_expected.json'), 'utf8'));
const state = JSON.parse(fs.readFileSync(path.join(ROOT, 'evidence/p2_state.json'), 'utf8')).reports;
async function frameHas(page, text, ms = 60000) {   // wait until the embedded Superset iframe shows `text`
  const t0 = Date.now(); let last = '';
  while (Date.now() - t0 < ms) { const fr = page.frames().find(f => f.url().includes('/embedded/')); if (fr) { try { last = (await fr.innerText('body')).replace(/\s+/g, ' '); if (last.includes(text)) return { ok: true, text: last }; } catch (e) {} } await page.waitForTimeout(800); }
  return { ok: false, text: last };
}
const lum = (h) => { const c = [1, 3, 5].map(i => parseInt(h.slice(i, i + 2), 16) / 255).map(v => v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4); return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]; };
const contrast = (a, b) => { const [x, y] = [lum(a), lum(b)].sort((p, q) => q - p); return (x + 0.05) / (y + 0.05); };
Object.assign(module.exports, { Rec, psql, py, expected, state, frameHas, contrast });
