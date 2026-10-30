import { loginCompanion, normalizeServerUrl, registerPrinter } from './lib/api.js';
import { buildTestEscposBytes } from './lib/escpos.js';
import {
  clearSession,
  ensureDeviceId,
  loadState,
  saveState,
} from './lib/storage.js';
import { printRaw } from './lib/usb.js';

const els = {
  serverUrl: document.getElementById('serverUrl'),
  username: document.getElementById('username'),
  password: document.getElementById('password'),
  signIn: document.getElementById('signIn'),
  signOut: document.getElementById('signOut'),
  sessionLine: document.getElementById('sessionLine'),
  printerLine: document.getElementById('printerLine'),
  choosePrinter: document.getElementById('choosePrinter'),
  testPrint: document.getElementById('testPrint'),
  pollNow: document.getElementById('pollNow'),
  statusLine: document.getElementById('statusLine'),
};

function setStatus(message) {
  els.statusLine.textContent = message || '';
}

function render(state) {
  els.serverUrl.value = state.serverUrl || '';
  if (!els.username.value) {
    els.username.value = state.username || '';
  }
  if (state.token && state.username) {
    els.sessionLine.textContent = `Signed in as ${state.username}`;
  } else {
    els.sessionLine.textContent = 'Not signed in.';
  }
  if (state.printer && state.printer.label) {
    els.printerLine.textContent = state.printer.label;
  } else {
    els.printerLine.textContent = 'No printer selected.';
  }
  if (state.statusMessage) {
    setStatus(state.statusMessage);
  }
}

function urlNeedsReplacement(value) {
  const base = normalizeServerUrl(value);
  if (!base) return true;
  let url;
  try {
    url = new URL(base);
  } catch {
    return true;
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return true;
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return true;
  if (url.port === '8000') return true;
  return false;
}

/** Origin of the SmartWagers tab, which is the only address this Chromebook can already reach. */
async function serverUrlFromOpenTab() {
  let tabs = [];
  try {
    tabs = await chrome.tabs.query({ active: true, lastFocusedWindow: true });
  } catch {
    return '';
  }
  const tab = tabs && tabs[0];
  if (!tab || !tab.url) return '';
  let url;
  try {
    url = new URL(tab.url);
  } catch {
    return '';
  }
  if (url.protocol !== 'http:' && url.protocol !== 'https:') return '';
  if (url.hostname === 'localhost' || url.hostname === '127.0.0.1') return '';
  return url.origin;
}

async function resolveServerUrl(typed) {
  const entered = normalizeServerUrl(typed);
  if (!urlNeedsReplacement(entered)) return entered;
  const fromTab = await serverUrlFromOpenTab();
  return fromTab || entered;
}

async function refresh() {
  const state = await loadState();
  render(state);
  if (urlNeedsReplacement(els.serverUrl.value)) {
    const fromTab = await serverUrlFromOpenTab();
    if (fromTab) els.serverUrl.value = fromTab;
  }
}

async function requestHostAccess(serverUrl) {
  const base = normalizeServerUrl(serverUrl);
  let origin;
  try {
    origin = new URL(base).origin;
  } catch {
    throw new Error('Invalid server URL.');
  }
  const pattern = `${origin}/*`;
  const already = await chrome.permissions.contains({ origins: [pattern] });
  if (!already) {
    const granted = await chrome.permissions.request({ origins: [pattern] });
    if (!granted) {
      throw new Error('Host permission was denied for the SmartWagers server.');
    }
  }
  const response = await chrome.runtime.sendMessage({
    type: 'register-content-script',
    serverUrl: base,
  });
  if (!response || !response.ok) {
    throw new Error((response && response.error) || 'Could not register page bridge.');
  }
  return origin;
}

function printerAddress(printer) {
  if (!printer) return '';
  return `${printer.vendorId}:${printer.productId}`;
}

els.signIn.addEventListener('click', async () => {
  els.signIn.disabled = true;
  try {
    const serverUrl = await resolveServerUrl(els.serverUrl.value);
    els.serverUrl.value = serverUrl;
    const username = String(els.username.value || '').trim();
    const password = String(els.password.value || '');
    if (!serverUrl || !username || !password) {
      throw new Error(
        'Open SmartWagers on this Chromebook first, then sign in here. '
          + 'Server URL must be that tab\'s address, including port 8080.',
      );
    }
    await requestHostAccess(serverUrl);
    const deviceId = await ensureDeviceId();
    const state = await loadState();
    const session = await loginCompanion({
      serverUrl,
      username,
      password,
      deviceId,
      printerName: (state.printer && state.printer.label) || '',
      printerAddress: printerAddress(state.printer),
    });
    await saveState({
      serverUrl: session.serverUrl,
      token: session.token,
      username: session.user,
      statusMessage: `Signed in as ${session.user}`,
    });
    els.password.value = '';
    if (state.printer) {
      await registerPrinter(
        { serverUrl: session.serverUrl, token: session.token },
        state.printer.label,
        printerAddress(state.printer),
      );
    }
    await refresh();
    await chrome.runtime.sendMessage({ type: 'poll-now' });
    await refresh();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message);
    await saveState({ statusMessage: message });
  } finally {
    els.signIn.disabled = false;
  }
});

els.signOut.addEventListener('click', async () => {
  await clearSession();
  els.password.value = '';
  await refresh();
});

els.choosePrinter.addEventListener('click', async () => {
  els.choosePrinter.disabled = true;
  try {
    await chrome.windows.create({
      url: chrome.runtime.getURL('picker.html'),
      type: 'normal',
      width: 440,
      height: 320,
      focused: true,
    });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message);
    await saveState({ statusMessage: message });
  } finally {
    els.choosePrinter.disabled = false;
  }
});

chrome.storage.onChanged.addListener((changes, area) => {
  if (area === 'local' && (changes.printer || changes.statusMessage || changes.token)) {
    refresh().catch(() => undefined);
  }
});

els.testPrint.addEventListener('click', async () => {
  els.testPrint.disabled = true;
  try {
    const state = await loadState();
    if (!state.printer) {
      throw new Error('Choose a USB printer first.');
    }
    setStatus('Sending test print…');
    await printRaw(state.printer, buildTestEscposBytes());
    const message = 'Test print sent.';
    setStatus(message);
    await saveState({ statusMessage: message });
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message);
    await saveState({ statusMessage: message });
  } finally {
    els.testPrint.disabled = false;
  }
});

els.pollNow.addEventListener('click', async () => {
  els.pollNow.disabled = true;
  try {
    const result = await chrome.runtime.sendMessage({ type: 'poll-now' });
    if (result && result.error) {
      setStatus(result.error);
    }
    await refresh();
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  } finally {
    els.pollNow.disabled = false;
  }
});

refresh().catch((error) => {
  setStatus(error instanceof Error ? error.message : String(error));
});
