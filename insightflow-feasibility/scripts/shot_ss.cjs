const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const [out, user, pw, dash] = process.argv.slice(2);
  const browser = await chromium.launch();
  const results = {};
  for (const [name, mode, vp] of [['light','default',{width:1280,height:900}],['dark','dark',{width:1280,height:900}],['mobile_light','default',{width:390,height:844}]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    await ctx.addCookies(JSON.parse(fs.readFileSync('/tmp/claude-0/work/ss_cookies.json','utf8')));
    await page.goto('http://127.0.0.1:8088/superset/welcome/', { waitUntil: 'domcontentloaded' });
    await page.evaluate((m) => localStorage.setItem('superset-theme-mode', m), mode);
    await page.goto(`http://127.0.0.1:8088/superset/dashboard/${dash}/?standalone=0`, { waitUntil: 'networkidle', timeout: 120000 });
    await page.waitForTimeout(9000);
    const info = await page.evaluate(() => {
      const cs = getComputedStyle(document.body);
      const btn = document.querySelector('.ant-btn-primary');
      return { bodyFont: cs.fontFamily, bodyBg: cs.backgroundColor, bodyColor: cs.color,
               primaryBtnBg: btn ? getComputedStyle(btn).backgroundColor : null,
               interLoaded: document.fonts.check('16px Inter'),
               hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth,
               supersetBranding: [...document.querySelectorAll('img,svg')].filter(e=>/superset/i.test(e.outerHTML.slice(0,300))).length };
    });
    results[name] = info;
    await page.screenshot({ path: `${out}/ss_${name}.png`, fullPage: false });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(results, null, 1));
})();
