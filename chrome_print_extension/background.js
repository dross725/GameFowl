import { ackJob, fetchPendingJobs, healthCheck, normalizeServerUrl } from './lib/api.js';
import { decodeEscposBase64 } from './lib/escpos.js';
import { loadState, saveState } from './lib/storage.js';
import { printRaw } from './lib/usb.js';

const POLL_ALARM = 'smartwagers-print-poll';
const CONTENT_SCRIPT_ID = 'smartwagers-print-bridge';

let busy = false;

async function setStatus(message) {
  await saveState({ statusMessage: String(message || '') });
}

function originFromServerUrl(serverUrl) {
  const base = normalizeServerUrl(serverUrl);
  if (!base) return null;
  try {
    return new URL(base).origin;
  } catch {
    return null;
  }
}

async function registerContentScript(origin) {
  try {
    await chrome.scripting.unregisterContentScripts({ ids: [CONTENT_SCRIPT_ID] });
  } catch {
    // Not registered yet.
  }
  await chrome.scripting.registerContentScripts([
    {
      id: CONTENT_SCRIPT_ID,
      js: ['content.js'],
      matches: [`${origin}/*`],
      runAt: 'document_start',
      persistAcrossSessions: true,
    },
  ]);
}

async function sessionFromState(state) {
  if (!state.token || !state.serverUrl) return null;
  return {
    serverUrl: normalizeServerUrl(state.serverUrl),
    token: state.token,
  };
}

async function handleJob(session, printer, job) {
  try {
    if (!printer) {
      await ackJob(session, job.id, 'failed', 'No printer selected');
      await setStatus(`Job #${job.id} failed: no printer selected`);
      return;
    }
    const bytes = decodeEscposBase64(job.escpos_base64);
    await setStatus(`Printing job #${job.id} (${job.endpoint})…`);
    await printRaw(printer, bytes);
    await ackJob(session, job.id, 'printed');
    await setStatus(`Printed job #${job.id}`);
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    try {
      await ackJob(session, job.id, 'failed', message);
    } catch {
      // Ignore ack failure.
    }
    await setStatus(`Job #${job.id} failed: ${message}`);
  }
}

async function pollPendingJobs() {
  if (busy) return { ok: true, skipped: true };
  busy = true;
  try {
    const state = await loadState();
    const session = await sessionFromState(state);
    if (!session) {
      return { ok: false, error: 'Not signed in.' };
    }
    const jobs = await fetchPendingJobs(session);
    for (const job of jobs) {
      await handleJob(session, state.printer, job);
    }
    if (!jobs.length) {
      try {
        const health = await healthCheck(session);
        await setStatus(
          health.pending_jobs
            ? `Signed in — ${health.pending_jobs} pending`
            : 'Signed in — waiting for receipts',
        );
      } catch {
        // Keep previous status if health fails.
      }
    }
    return { ok: true, count: jobs.length };
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    await setStatus(message);
    return { ok: false, error: message };
  } finally {
    busy = false;
  }
}

async function ensurePollAlarm() {
  await chrome.alarms.create(POLL_ALARM, { periodInMinutes: 1 });
}

chrome.runtime.onInstalled.addListener(() => {
  ensurePollAlarm().catch(() => undefined);
});

chrome.runtime.onStartup.addListener(() => {
  ensurePollAlarm().catch(() => undefined);
  pollPendingJobs().catch(() => undefined);
});

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === POLL_ALARM) {
    pollPendingJobs().catch(() => undefined);
  }
});

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  const type = message && message.type;
  if (type === 'job-queued' || type === 'poll-now') {
    pollPendingJobs()
      .then((result) => sendResponse(result))
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return true;
  }
  if (type === 'register-content-script') {
    const origin = originFromServerUrl(message.serverUrl);
    if (!origin) {
      sendResponse({ ok: false, error: 'Invalid server URL.' });
      return false;
    }
    registerContentScript(origin)
      .then(() => sendResponse({ ok: true, origin }))
      .catch((error) => {
        sendResponse({
          ok: false,
          error: error instanceof Error ? error.message : String(error),
        });
      });
    return true;
  }
  return false;
});

ensurePollAlarm().catch(() => undefined);
