import { buildTestEscposBytes } from './lib/escpos.js';
import { loadState } from './lib/storage.js';
import { printRaw } from './lib/usb.js';

const statusLine = document.getElementById('statusLine');

function setStatus(message) {
  if (statusLine) statusLine.textContent = message || '';
}

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.type !== 'print-usb') return;
  setStatus('Printing…');
  const bytes = new Uint8Array(message.bytes || []);
  printRaw(message.printer, bytes)
    .then(() => {
      setStatus('Printed.');
      sendResponse({ ok: true });
    })
    .catch((error) => {
      const text = error instanceof Error ? error.message : String(error);
      setStatus(text);
      sendResponse({ ok: false, error: text });
    });
  return true;
});

const mode = new URLSearchParams(window.location.search).get('mode');
if (mode === 'test') {
  const state = await loadState();
  setStatus('Sending test print…');
  try {
    if (!state.printer) {
      throw new Error('Choose a USB printer first.');
    }
    await printRaw(state.printer, buildTestEscposBytes());
    setStatus('Test print sent. You can close this tab.');
  } catch (error) {
    setStatus(error instanceof Error ? error.message : String(error));
  }
} else {
  setStatus('Waiting for receipts. Leave this tab open.');
  chrome.runtime.sendMessage({ type: 'print-page-ready' });
}
