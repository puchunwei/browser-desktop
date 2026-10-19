// Check Chrome's own sandbox diagnostics without navigating an existing tab.
// node sandbox.mjs <loopback-cdp-port> <private-report-file>
import assert from 'node:assert/strict';
import { writeFileSync } from 'node:fs';

const [port, output] = process.argv.slice(2);
assert(/^\d+$/.test(port) && Number(port) > 0 && Number(port) < 65536 && output);
const version = await (await fetch(`http://127.0.0.1:${port}/json/version`)).json();
const ws = new WebSocket(version.webSocketDebuggerUrl);
await new Promise((resolve, reject) => { ws.onopen = resolve; ws.onerror = reject; });
let sequence = 0;
const pending = new Map();
ws.onmessage = ({ data }) => {
    const result = JSON.parse(data);
    const request = pending.get(result.id);
    if (!request) return;
    clearTimeout(request.timer);
    pending.delete(result.id);
    result.error ? request.reject(Error(result.error.message)) : request.resolve(result.result);
};
function call(method, params = {}, sessionId) {
    return new Promise((resolve, reject) => {
        const id = ++sequence;
        const timer = setTimeout(() => { pending.delete(id); reject(Error(`CDP timeout: ${method}`)); }, 10000);
        pending.set(id, { resolve, reject, timer });
        ws.send(JSON.stringify({ id, method, params, ...(sessionId ? { sessionId } : {}) }));
    });
}
async function evaluate(sessionId, expression) {
    const result = await call('Runtime.evaluate', { expression, returnByValue: true }, sessionId);
    assert(!result.exceptionDetails, 'Sandbox diagnostic evaluation failed');
    return result.result.value;
}
const created = [];
const report = { checkedAt: new Date().toISOString(), browser: version.Browser, passed: false };
async function open(url) {
    const { targetId } = await call('Target.createTarget', { url });
    created.push(targetId);
    return (await call('Target.attachToTarget', { targetId, flatten: true })).sessionId;
}
try {
    const sandbox = await open('chrome://sandbox/');
    let rows = [];
    for (let attempt = 0; attempt < 50; attempt++) {
        rows = await evaluate(sandbox, '[...document.querySelectorAll("tr")].map(row=>[...row.querySelectorAll("td")].map(cell=>cell.textContent.trim())).filter(cells=>cells.length===2)');
        if (rows.some(([name]) => name === 'Seccomp-BPF sandbox')) break;
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    report.sandbox = Object.fromEntries(rows);
    assert.equal(report.sandbox['PID namespaces'], 'Yes', 'Chrome PID namespace sandbox is disabled');
    assert.equal(report.sandbox['Network namespaces'], 'Yes', 'Chrome network namespace sandbox is disabled');
    assert.equal(report.sandbox['Seccomp-BPF sandbox'], 'Yes', 'Chrome seccomp-BPF sandbox is disabled');
    const info = await open('chrome://version/');
    let commandLine;
    for (let attempt = 0; attempt < 50; attempt++) {
        commandLine = await evaluate(info, 'document.querySelector("#command_line")?.textContent');
        if (commandLine) break;
        await new Promise(resolve => setTimeout(resolve, 100));
    }
    assert(commandLine, 'Chrome command-line diagnostics unavailable');
    report.noSandboxFlag = /(?:^|\s)--no-sandbox(?:\s|$)/.test(commandLine);
    assert.equal(report.noSandboxFlag, false, 'Chrome still has --no-sandbox');
    report.passed = true;
    console.log(JSON.stringify(report));
} finally {
    for (const targetId of created) await call('Target.closeTarget', { targetId }).catch(() => {});
    ws.close();
    writeFileSync(output, JSON.stringify(report, null, 2) + '\n', { mode: 0o600 });
}
