/**
 * Production routing tests for print_client.js.
 * Run: node SmartWagers/static/SmartWagers/print_client_routing.test.mjs
 */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import { fileURLToPath } from 'node:url';

const source = fs.readFileSync(
  fileURLToPath(new URL('./print_client.js', import.meta.url)),
  'utf8',
);

function response(ok, body = {}, status = ok ? 200 : 503) {
  return { ok, status, json: async () => body };
}

function loadClient({ ua, mode = 'auto', fetch }) {
  const values = new Map([['smartwagersPrintMode', mode]]);
  const posted = [];
  const window = {
    location: { origin: 'http://smartwagers.test' },
    postMessage: (data, targetOrigin) => {
      posted.push({ data, targetOrigin });
    },
  };
  const context = {
    window,
    navigator: { userAgent: ua },
    localStorage: {
      getItem: (key) => values.get(key) ?? null,
      setItem: (key, value) => values.set(key, String(value)),
    },
    document: { cookie: '', querySelector: () => null },
    fetch,
    AbortController,
    setTimeout,
    clearTimeout,
    Date,
    JSON,
    decodeURIComponent,
  };
  vm.runInNewContext(source, context, { filename: 'print_client.js' });
  return { api: window.SmartWagersPrint, posted };
}

const WINDOWS_UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120 Safari/537.36';
const ANDROID_UA =
  'Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 Chrome/120 Mobile Safari/537.36';
const CHROMEOS_UA =
  'Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 Chrome/120 Safari/537.36';

{
  const { api: client } = loadClient({ ua: WINDOWS_UA, fetch: async () => response(false) });
  assert.equal(client.isChromeOS(WINDOWS_UA), false);
  assert.equal(client.isLikelyMobile(ANDROID_UA), true);
  assert.equal(client.prefersCompanionQueue(CHROMEOS_UA), true);
}

{
  const calls = [];
  const { api: client } = loadClient({
    ua: WINDOWS_UA,
    fetch: async (url) => {
      calls.push(url);
      return response(false, { error: 'offline' });
    },
  });
  const result = await client.printWagerReceipt({ transaction_id: '1' });
  assert.equal(result.ok, false);
  assert.equal(result.via, 'local');
  assert.deepEqual(calls, ['http://127.0.0.1:8765/print-wager']);
}

{
  const calls = [];
  const { api: client, posted } = loadClient({
    ua: CHROMEOS_UA,
    fetch: async (url) => {
      calls.push(url);
      if (url.endsWith('/health')) return response(false);
      return response(true, { ok: true, job_id: 7 });
    },
  });
  const result = await client.printWagerReceipt({ transaction_id: '2' });
  assert.equal(result.ok, true);
  assert.equal(result.via, 'server');
  assert.deepEqual(calls, ['http://127.0.0.1:8765/health', '/api/print-jobs/']);
  assert.equal(posted.length, 1);
  // Compare via JSON — the payload object is created inside the vm sandbox.
  assert.deepEqual(JSON.parse(JSON.stringify(posted[0].data)), {
    source: 'smartwagers-print',
    type: 'job-queued',
    job_id: 7,
  });
  assert.equal(posted[0].targetOrigin, 'http://smartwagers.test');
}

{
  const calls = [];
  const { api: client, posted } = loadClient({
    ua: CHROMEOS_UA,
    mode: 'local',
    fetch: async (url) => {
      calls.push(url);
      return response(false, { error: 'offline' });
    },
  });
  const result = await client.printWagerReceipt({ transaction_id: '3' });
  assert.equal(result.via, 'local');
  assert.deepEqual(calls, ['http://127.0.0.1:8765/print-wager']);
  assert.equal(posted.length, 0);
}

{
  const calls = [];
  const { api: client, posted } = loadClient({
    ua: WINDOWS_UA,
    mode: 'server',
    fetch: async (url) => {
      calls.push(url);
      return response(true, { ok: true, job_id: 8 });
    },
  });
  const result = await client.printWagerReceipt({ transaction_id: '4' });
  assert.equal(result.via, 'server');
  assert.deepEqual(calls, ['/api/print-jobs/']);
  assert.equal(posted.length, 0);
}

console.log('All print_client production routing cases passed.');
