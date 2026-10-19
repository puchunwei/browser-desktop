// Carries the open tabs across a switch and proves the login state survived.
// Save an independent inventory even though Chromium restores its last session.
//   node tabs.mjs save    <cdp-port> <file>   tabs + cookie count -> file
//   node tabs.mjs restore <cdp-port> <file>   reopen saved tabs that are not open
//   node tabs.mjs compare <cdp-port> <file>   all tabs open, cookies >= 90% of saved
import { readFileSync, writeFileSync } from 'node:fs';

const [mode, port, file] = process.argv.slice(2);
if (!['save', 'restore', 'compare'].includes(mode) || !port || !file) {
    console.error('usage: node tabs.mjs save|restore|compare <cdp-port> <file>');
    process.exit(2);
}
const base = `http://127.0.0.1:${port}`;

async function browserCall(method, params = {}) {
    const { webSocketDebuggerUrl } = await (await fetch(`${base}/json/version`)).json();
    const ws = new WebSocket(webSocketDebuggerUrl);
    return new Promise((resolve, reject) => {
        ws.onopen = () => ws.send(JSON.stringify({ id: 1, method, params }));
        ws.onmessage = (event) => {
            const reply = JSON.parse(event.data);
            if (reply.id !== 1) return;
            ws.close();
            reply.error ? reject(new Error(reply.error.message)) : resolve(reply.result);
        };
        ws.onerror = () => reject(new Error(`CDP websocket failed on ${port}`));
    });
}

async function snapshot() {
    const targets = await (await fetch(`${base}/json/list`)).json();
    const tabs = targets.filter((t) => t.type === 'page' && /^https?:/.test(t.url)).map((t) => t.url);
    const { cookies } = await browserCall('Storage.getCookies');
    return { tabs, cookieCount: cookies.length };
}

const current = await snapshot();
if (mode === 'save') {
    writeFileSync(file, JSON.stringify(current, null, 2), { mode: 0o600 });
    console.log(`saved ${current.tabs.length} tabs, ${current.cookieCount} cookies`);
} else {
    const saved = JSON.parse(readFileSync(file, 'utf8'));
    const missing = saved.tabs.filter((url) => !current.tabs.includes(url));
    if (mode === 'restore') {
        for (const url of missing) await browserCall('Target.createTarget', { url });
        console.log(`reopened ${missing.length} of ${saved.tabs.length} tabs`);
    } else {
        const cookiesOk = current.cookieCount >= Math.floor(saved.cookieCount * 0.9);
        console.log(`tabs missing ${missing.length}/${saved.tabs.length}; cookies ${current.cookieCount} (saved ${saved.cookieCount})`);
        if (missing.length || !cookiesOk) process.exit(1);
    }
}
