// A disposable browser tab whose pattern and click response can only be seen over RDP.
import { readFileSync, writeFileSync } from 'node:fs';
const [mode, port, file] = process.argv.slice(2);
if (!['open', 'close'].includes(mode) || !port || !file) throw new Error('usage: visual-target.mjs open|close <cdp-port> <state-file>');
const base = `http://127.0.0.1:${port}`;
async function call(method, params) {
    const { webSocketDebuggerUrl } = await (await fetch(`${base}/json/version`)).json();
    return new Promise((resolve, reject) => {
        const ws = new WebSocket(webSocketDebuggerUrl);
        const timer = setTimeout(() => { ws.close(); reject(new Error('CDP timed out')); }, 10000);
        ws.onopen = () => ws.send(JSON.stringify({ id: 1, method, params }));
        ws.onmessage = ({ data }) => {
            const reply = JSON.parse(data);
            if (reply.id !== 1) return;
            clearTimeout(timer); ws.close();
            reply.error ? reject(new Error(reply.error.message)) : resolve(reply.result);
        };
        ws.onerror = () => { clearTimeout(timer); reject(new Error('CDP websocket failed')); };
    });
}
if (mode === 'open') {
    const html = `<title>RDP visual verification</title>
<style>body{margin:0;display:grid;grid-template-columns:1fr 1fr;height:100vh}div{display:grid;place-items:center;font:32px sans-serif;color:white}#a{cursor:default}#b{cursor:pointer}#c{cursor:text}</style>
<body onpointerdown="const a=document.getElementById('a');a.dataset.clicked=a.dataset.clicked==='yes'?'no':'yes';a.style.background=a.dataset.clicked==='yes'?'rgb(165,45,210)':'rgb(235,52,67)'">
<div id=a style="background:rgb(235,52,67)">RDP desktop verification</div><div id=b style="background:rgb(40,190,90)">Mouse input</div><div id=c style="background:rgb(35,95,220)">Session reuse</div><div style="background:rgb(235,185,35)">Reconnect</div>`;
    const { targetId } = await call('Target.createTarget', { url: `data:text/html,${encodeURIComponent(html)}` });
    writeFileSync(file, JSON.stringify({ targetId }), { mode: 0o600 });
    await call('Target.activateTarget', { targetId });
} else {
    const { targetId } = JSON.parse(readFileSync(file, 'utf8'));
    const result = await call('Target.closeTarget', { targetId });
    if (!result.success) throw new Error('could not close the test tab');
}
