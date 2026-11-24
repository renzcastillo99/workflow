// Copies the app page (../hr-system.html) into app/index.html so there is one source of truth.
const fs = require('fs'), path = require('path');
const src = path.join(__dirname, '..', '..', 'hr-system.html');
const dest = path.join(__dirname, '..', 'app', 'index.html');
fs.mkdirSync(path.dirname(dest), { recursive: true });
fs.copyFileSync(src, dest);
console.log('Synced hr-system.html -> app/index.html');
