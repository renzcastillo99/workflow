const { contextBridge, ipcRenderer } = require('electron');
// The only things the page may ask the app to do: fetch a link, and open a sign-in window.
contextBridge.exposeInMainWorld('egisBridge', {
  fetchUrl: (url) => ipcRenderer.invoke('egis:fetch', String(url)),
  signIn: (url) => ipcRenderer.invoke('egis:signin', String(url))
});
