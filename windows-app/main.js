const { app, BrowserWindow, Menu, shell, ipcMain, session } = require('electron');
const path = require('path');

const SP_PARTITION = 'persist:egis-sharepoint';   // keeps the Microsoft sign-in between launches
const MAX_BYTES = 10 * 1024 * 1024;
let win = null;

// Only https links to public hosts (http/local hosts only when testing with EGIS_ALLOW_LOCAL=1).
function checkUrl(u) {
  let url;
  try { url = new URL(u); } catch (e) { throw new Error('That is not a valid link.'); }
  const local = process.env.EGIS_ALLOW_LOCAL === '1';
  if (url.protocol !== 'https:' && !(local && url.protocol === 'http:')) throw new Error('Only https links are supported.');
  const h = url.hostname.toLowerCase();
  const priv = h === 'localhost' || h.endsWith('.local') || h.includes(':') || /^(127\.|10\.|192\.168\.|169\.254\.|172\.(1[6-9]|2\d|3[01])\.|0\.)/.test(h);
  if (priv && !local) throw new Error('That address is not allowed.');
  return url.toString();
}
function fileNameFrom(disposition) {
  let m = /filename\*=UTF-8''([^;]+)/i.exec(disposition || '');
  if (m) { try { return decodeURIComponent(m[1]); } catch (e) { /* fall through */ } }
  m = /filename="?([^";]+)"?/i.exec(disposition || '');
  return m ? m[1] : '';
}

ipcMain.handle('egis:fetch', async (event, u) => {
  try {
    const url = checkUrl(u);
    const ses = session.fromPartition(SP_PARTITION);
    const res = await ses.fetch(url, { redirect: 'follow' });
    const len = Number(res.headers.get('content-length') || 0);
    if (len > MAX_BYTES) return { ok: false, error: 'The file is too big (over 10 MB).' };
    const buf = Buffer.from(await res.arrayBuffer());
    if (buf.length > MAX_BYTES) return { ok: false, error: 'The file is too big (over 10 MB).' };
    return { ok: res.ok, status: res.status, contentType: res.headers.get('content-type') || '',
             filename: fileNameFrom(res.headers.get('content-disposition')), data: buf };
  } catch (err) {
    return { ok: false, error: String((err && err.message) || err) };
  }
});

ipcMain.handle('egis:signin', (event, u) => new Promise((resolve) => {
  let url;
  try { url = checkUrl(u); } catch (err) { return resolve({ ok: false, error: err.message }); }
  const parent = BrowserWindow.fromWebContents(event.sender) || undefined;
  const w = new BrowserWindow({
    width: 560, height: 740, parent, modal: !!parent,
    title: 'Sign in to Microsoft - close this window when you are done',
    webPreferences: { partition: SP_PARTITION, sandbox: true, contextIsolation: true, nodeIntegration: false }
  });
  w.setMenu(null);
  w.on('page-title-updated', (e) => e.preventDefault());
  w.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
  w.on('closed', () => resolve({ ok: true }));
  w.loadURL(url).catch(() => { /* the window shows its own error page */ });
}));

if (!app.requestSingleInstanceLock()) {
  app.quit();            // already open: don't start a second copy
} else {
  app.on('second-instance', () => {
    if (win) { if (win.isMinimized()) win.restore(); win.focus(); }
  });

  app.whenReady().then(() => {
    Menu.setApplicationMenu(null);
    win = new BrowserWindow({
      width: 1100, height: 800, minWidth: 360, minHeight: 500,
      title: 'EGIS HR', icon: path.join(__dirname, 'icon.png'), backgroundColor: '#131212',
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true, preload: path.join(__dirname, 'preload.js') }
    });
    win.loadFile(path.join(__dirname, 'app', 'index.html'));
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('file://')) e.preventDefault(); });
    win.on('page-title-updated', (e) => e.preventDefault());   // keep the title "EGIS HR"
    win.on('closed', () => { win = null; });

    // After an export/backup is saved, show the file in Explorer so it is easy to find.
    win.webContents.session.on('will-download', (event, item) => {
      item.once('done', (e, state) => { if (state === 'completed') shell.showItemInFolder(item.getSavePath()); });
    });
  });

  app.on('window-all-closed', () => app.quit());
}
