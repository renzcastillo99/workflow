const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const tok = fs.readFileSync('/tmp/claude-0/work/tok.txt','utf8').trim();
  const out = process.argv[2];
  const browser = await chromium.launch();
  const results = {};
  for (const [name, hash, vp] of [['light','#bordered=false&titled=true',{width:1280,height:900}],['night','#bordered=false&titled=true&theme=night',{width:1280,height:900}],['mobile_light','#bordered=false&titled=true',{width:390,height:844}]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2 });
    const page = await ctx.newPage();
    await page.goto(`http://127.0.0.1:3000/embed/dashboard/${tok}${hash}`, { waitUntil: 'networkidle', timeout: 90000 });
    await page.waitForTimeout(6000);
    const text = (await page.innerText('body')).replace(/\s+/g,' ');
    const info = await page.evaluate(() => {
      const cs = getComputedStyle(document.body);
      const links = [...document.querySelectorAll('a')].map(a => a.textContent.trim()+' -> '+a.href).filter(t=>/metabase/i.test(t));
      return { bodyFont: cs.fontFamily, bodyBg: cs.backgroundColor, bodyColor: cs.color, brandingLinks: links.slice(0,3),
               hscroll: document.documentElement.scrollWidth > document.documentElement.clientWidth };
    });
    results[name] = { poweredBy: /Powered by Metabase/i.test(text), textSample: text.slice(0,160), ...info };
    await page.screenshot({ path: `${out}/mb_embed_${name}.png`, fullPage: true });
    await ctx.close();
  }
  await browser.close();
  console.log(JSON.stringify(results, null, 1));
})();
