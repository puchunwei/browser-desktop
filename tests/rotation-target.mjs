// Synthetic colored click targets for a single connection's rotation regression.
import { readFileSync, writeFileSync } from 'node:fs';
const [mode, port, file] = process.argv.slice(2);
if (!['open', 'close'].includes(mode) || !port || !file) throw new Error('usage: rotation-target.mjs open|close <cdp-port> <state-file>');
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
    const colors = ['235,52,67', '40,190,90', '35,95,220', '235,185,35'];
    const html = `<meta charset="utf-8"><title>RDP rotation verification</title>
<style>body{margin:0;display:grid;grid-template-columns:1fr 1fr;height:100vh}button{border:0;padding:0;font:24px sans-serif;color:white}</style>
${colors.map((color, i) => `<button id="zone-${i}" style="background:rgb(${color})" onpointerdown="if(event.isTrusted){this.dataset.clicked=this.dataset.clicked==='yes'?'no':'yes';this.style.background=this.dataset.clicked==='yes'?'rgb(165,45,210)':'rgb(${color})'}">Target ${i + 1}</button>`).join('')}`;
    const { targetId } = await call('Target.createTarget', { url: `data:text/html,${encodeURIComponent(html)}` });
    writeFileSync(file, JSON.stringify({ targetId }), { mode: 0o600 });
    await call('Target.activateTarget', { targetId });
} else {
    const { targetId } = JSON.parse(readFileSync(file, 'utf8'));
    if (!(await call('Target.closeTarget', { targetId })).success) throw new Error('could not close rotation test tab');
}
