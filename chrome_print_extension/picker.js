import { registerPrinter } from './lib/api.js';
import { loadState, saveState } from './lib/storage.js';
import { choosePrinter } from './lib/usb.js';

const statusLine = document.getElementById('statusLine');
const selectPrinter = document.getElementById('selectPrinter');

function setStatus(message) {
  statusLine.textContent = message || '';
}

function printerAddress(printer) {
  if (!printer) return '';
  return `${printer.vendorId}:${printer.productId}`;
}

selectPrinter.addEventListener('click', async () => {
  selectPrinter.disabled = true;
  try {
    const printer = await choosePrinter();
    await saveState({
      printer,
      statusMessage: `Selected ${printer.label}`,
    });
    const state = await loadState();
    if (state.token && state.serverUrl) {
      await registerPrinter(
        { serverUrl: state.serverUrl, token: state.token },
        printer.label,
        printerAddress(printer),
      );
    }
    setStatus(`Selected ${printer.label}`);
    window.close();
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    setStatus(message);
    await saveState({ statusMessage: message });
    selectPrinter.disabled = false;
  }
});
