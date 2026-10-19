// Disposable fixture: CDP creates and reads a page; only RDP supplies text.
import { readFileSync, writeFileSync } from 'node:fs';
const [mode, port, file, expected = '中A1文B2输入C3测试D4'] = process.argv.slice(2);
if (!['open', 'read', 'check', 'close'].includes(mode) || !port || !file) {
    throw new Error('usage: unicode-target.mjs open|read|check|close <synthetic-cdp-port> <state-file> [expected]');
}
const { webSocketDebuggerUrl } = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const ws = new WebSocket(webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let sequence = 0;
const pending = new Map();
ws.onmessage = ({ data }) => {
    const reply = JSON.parse(data);
    const entry = pending.get(reply.id);
    if (!entry) return;
    pending.delete(reply.id);
    clearTimeout(entry.timer);
    reply.error ? entry.reject(new Error(reply.error.message)) : entry.resolve(reply.result);
};
function call(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
        const id = ++sequence;
        const timer = setTimeout(() => { pending.delete(id); reject(new Error(`${method} timed out`)); }, 10000);
        pending.set(id, { resolve, reject, timer });
        ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
}
try {
    if (mode === 'open') {
        const html = `<!doctype html><meta charset=utf-8><title>RDP Unicode verification</title>
<style>body{margin:0;padding:30px;background:rgb(35,95,220);font:30px sans-serif;color:white}input{display:block;box-sizing:border-box;width:100%;height:330px;margin-top:30px;border:6px solid white;background:rgb(27,181,91);font:38px sans-serif}</style>
<h1>RDP Unicode verification</h1><input id=rdp-unicode autofocus autocomplete=off>
<script>window.inputEvents=[];window.keyEvents=[];document.querySelector('input').addEventListener('input',e=>inputEvents.push({trusted:e.isTrusted,data:e.data,inputType:e.inputType}));document.addEventListener('keydown',e=>keyEvents.push({key:e.key,ctrl:e.ctrlKey,trusted:e.isTrusted}));</script>`;
        const { targetId } = await call('Target.createTarget', { url: `data:text/html,${encodeURIComponent(html)}` });
        writeFileSync(file, JSON.stringify({ targetId }), { mode: 0o600 });
        await call('Target.activateTarget', { targetId });
    } else {
        const { targetId } = JSON.parse(readFileSync(file, 'utf8'));
        if (mode === 'close') {
            const result = await call('Target.closeTarget', { targetId });
            if (!result.success) throw new Error('could not close synthetic Unicode page');
        } else {
            const { sessionId } = await call('Target.attachToTarget', { targetId, flatten: true });
            const { result, exceptionDetails } = await call('Runtime.evaluate', {
                expression: `JSON.stringify({title:document.title,value:document.querySelector('#rdp-unicode')?.value,events:window.inputEvents,keys:window.keyEvents})`,
                returnByValue: true,
            }, sessionId);
            if (exceptionDetails) throw new Error('could not read synthetic Unicode page');
            const value = JSON.parse(result.value);
            if (value.title !== 'RDP Unicode verification') throw new Error('synthetic target identity changed');
            console.log(JSON.stringify(value));
            if (mode === 'check' && (value.value !== expected || !value.events.length || value.events.some(event => !event.trusted))) {
                throw new Error(`RDP Unicode input mismatch: expected ${JSON.stringify(expected)}, received ${JSON.stringify(value.value)}`);
            }
            const inserted = value.events.filter(event => event.inputType === 'insertText').map(event => event.data ?? '').join('');
            if (mode === 'check' && inserted !== expected.repeat(process.env.VERIFY_SHORTCUTS === '1' ? 2 : 1)) {
                throw new Error('RDP Unicode event order mismatch, including the first input before shortcut replacement');
            }
            if (mode === 'check' && process.env.VERIFY_SHORTCUTS === '1' && (value.keys.filter(event => event.ctrl && event.key.toLowerCase() === 'a' && event.trusted).length < 2 ||
                    !['c', 'v'].every(key => value.keys.some(event => event.ctrl && event.key.toLowerCase() === key && event.trusted)) ||
                    !value.events.some(event => event.inputType === 'insertFromPaste'))) {
                throw new Error('RDP native and mixed Unicode modifier shortcuts did not reach the fixture');
            }
        }
    }
} finally {
    ws.close();
}
