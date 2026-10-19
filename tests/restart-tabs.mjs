// Run only against a disposable profile. The check must not reopen missing tabs.
import { readFileSync, writeFileSync } from 'node:fs';
const [mode, port, file] = process.argv.slice(2);
if (!['prepare', 'check'].includes(mode) || !port || !file) throw Error('usage: restart-tabs.mjs prepare|check <cdp-port> <state-file>');
const base = `http://127.0.0.1:${port}`;
async function call(method, params) {
    const { webSocketDebuggerUrl } = await (await fetch(`${base}/json/version`)).json();
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(webSocketDebuggerUrl);
        const timer = setTimeout(() => { ws.close(); reject(Error('CDP timeout')); }, 10000);
        ws.onopen = () => ws.send(JSON.stringify({ id: 1, method, params }));
        ws.onmessage = ({ data }) => {
            const r = JSON.parse(data);
            if (r.id !== 1) return;
            clearTimeout(timer); ws.close();
            r.error ? reject(Error(r.error.message)) : resolve(r.result);
        };
        ws.onerror = () => { clearTimeout(timer); reject(Error('CDP connection failed')); };
    });
}
if (mode === 'prepare') {
    const urls = ['first', 'second', 'third'].map(name => `data:text/html,<title>Retained ${name}</title>${name}`);
    for (const url of urls) await call('Target.createTarget', { url });
    writeFileSync(file, JSON.stringify(urls), { mode: 0o600 });
    console.log('Prepared three synthetic tabs for a container restart');
} else {
    const urls = JSON.parse(readFileSync(file, 'utf8'));
    const deadline = Date.now() + 30000;
    let missing;
    do {
        const tabs = await (await fetch(`${base}/json/list`)).json();
        missing = urls.filter(url => !tabs.some(t => t.type === 'page' && t.url === url));
        if (!missing.length) break;
        await new Promise(resolve => setTimeout(resolve, 500));
    } while (Date.now() < deadline);
    if (missing.length) throw Error(`Restart lost ${missing.length}/${urls.length} synthetic tabs`);
    console.log('OK: all three tabs automatically survived a container restart');
}
