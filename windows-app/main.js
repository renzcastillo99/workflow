const { app, BrowserWindow, Menu, shell } = require('electron');
const path = require('path');

let win = null;

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
      title: 'Café HR', icon: path.join(__dirname, 'icon.png'), backgroundColor: '#FFF8F0',
      webPreferences: { contextIsolation: true, nodeIntegration: false, sandbox: true }
    });
    win.loadFile(path.join(__dirname, 'app', 'index.html'));
    win.webContents.setWindowOpenHandler(() => ({ action: 'deny' }));
    win.webContents.on('will-navigate', (e, url) => { if (!url.startsWith('file://')) e.preventDefault(); });
    win.on('page-title-updated', (e) => e.preventDefault());   // keep the title "Café HR"
    win.on('closed', () => { win = null; });

    // After an export/backup is saved, show the file in Explorer so it is easy to find.
    win.webContents.session.on('will-download', (event, item) => {
      item.once('done', (e, state) => { if (state === 'completed') shell.showItemInFolder(item.getSavePath()); });
    });
  });

  app.on('window-all-closed', () => app.quit());
}
