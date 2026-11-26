const { chromium } = require('playwright');
(async () => {
  const [out, uuid, tag] = process.argv.slice(2);
  const browser = await chromium.launch(); const res = {};
  for (const [name, vp] of [['desktop',{width:1280,height:900}],['mobile',{width:390,height:844}]]) {
    const ctx = await browser.newContext({ viewport: vp, deviceScaleFactor: 2 }); const page = await ctx.newPage();
    const msgs = []; page.on('console', m => { if (m.type()==='error') msgs.push(m.text().slice(0,160)); });
    await page.goto(`http://127.0.0.1:9000/?uuid=${uuid}&dash=bench_1m`, { waitUntil: 'networkidle', timeout: 90000 });
    await page.waitForTimeout(12000);
    const fr = page.frames().find(f => f.url().includes('/embedded/'));
    let text = null, hscroll = null;
    if (fr) { try { text = (await fr.innerText('body')).replace(/\s+/g,' ').slice(0,260); hscroll = await fr.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth); } catch(e) { text = 'ERR '+e.message.slice(0,80); } }
    res[name] = { iframeFound: !!fr, iframeUrl: fr && fr.url(), bodyText: text, hscroll, consoleErrors: msgs.slice(0,3) };
    await page.screenshot({ path: `${out}/ss_embed_${tag}_${name}.png` }); await ctx.close();
  }
  await browser.close(); console.log(JSON.stringify(res, null, 1));
})();
