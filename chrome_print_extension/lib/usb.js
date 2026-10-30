/**
 * Raw ESC/POS over WebUSB bulk-OUT.
 *
 * chrome.usb is a Chrome Apps API and is undefined in extensions, which
 * throws "Cannot read properties of undefined (reading 'getUserSelectedDevices')".
 * Extensions use navigator.usb instead. requestDevice() has to run in a
 * normal window (picker.html): service workers cannot show the chooser,
 * and extension popups often cannot either.
 */

const CHUNK_SIZE = 16384;

/** Printer class (7) and vendor-specific (255). WebUSB rejects an empty filter list. */
const DEVICE_FILTERS = [
  { classCode: 7 },
  { classCode: 0xff },
];

function requireWebUsb() {
  if (!navigator.usb) {
    throw new Error('WebUSB is not available in this Chrome window.');
  }
}

export function printerLabel(device) {
  const name = device.productName || device.manufacturerName || 'USB printer';
  return `${name} (${device.vendorId}:${device.productId})`;
}

export function printerIdentity(device) {
  let serialNumber = '';
  try {
    serialNumber = device.serialNumber || '';
  } catch {
    serialNumber = '';
  }
  return {
    vendorId: device.vendorId,
    productId: device.productId,
    serialNumber,
    productName: device.productName || '',
    manufacturerName: device.manufacturerName || '',
    label: printerLabel(device),
  };
}

/** User-gesture picker. Call from picker.html, not the extension popup. */
export async function choosePrinter() {
  requireWebUsb();
  if (typeof navigator.usb.requestDevice !== 'function') {
    throw new Error('This page cannot show the USB device picker.');
  }
  let device;
  try {
    device = await navigator.usb.requestDevice({ filters: DEVICE_FILTERS });
  } catch (error) {
    if (error && error.name === 'NotFoundError') {
      throw new Error('No USB printer selected.');
    }
    throw error;
  }
  return printerIdentity(device);
}

async function findDevice(printer) {
  requireWebUsb();
  const devices = await navigator.usb.getDevices();
  const match = (devices || []).find((device) => {
    if (device.vendorId !== printer.vendorId || device.productId !== printer.productId) {
      return false;
    }
    if (!printer.serialNumber) return true;
    try {
      return !device.serialNumber || device.serialNumber === printer.serialNumber;
    } catch {
      return true;
    }
  });
  if (!match) {
    throw new Error(
      'USB printer not found. Reconnect it, then Choose printer again.',
    );
  }
  return match;
}

function findBulkOut(device) {
  for (const config of device.configurations || []) {
    for (const iface of config.interfaces || []) {
      for (const alt of iface.alternates || []) {
        for (const endpoint of alt.endpoints || []) {
          if (endpoint.type === 'bulk' && endpoint.direction === 'out') {
            return {
              configurationValue: config.configurationValue,
              interfaceNumber: iface.interfaceNumber,
              alternateSetting: alt.alternateSetting,
              endpointNumber: endpoint.endpointNumber,
            };
          }
        }
      }
    }
  }
  return null;
}

/**
 * Open, write chunked bulk-OUT, release, close.
 * Do not leave the interface open — the service worker may sleep.
 */
export async function printRaw(printer, bytes) {
  if (!printer) {
    throw new Error('No printer selected.');
  }
  const payload = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes || []);
  if (!payload.length) {
    throw new Error('ESC/POS payload is empty.');
  }

  const device = await findDevice(printer);
  const bulk = findBulkOut(device);
  if (!bulk) {
    throw new Error(
      'This USB device has no bulk-OUT printer endpoint. '
        + 'Serial adapters (CH340 and similar) are not supported — use a raw ESC/POS USB printer.',
    );
  }

  await device.open();
  try {
    if (device.configuration === null) {
      await device.selectConfiguration(bulk.configurationValue);
    }
    if (bulk.alternateSetting) {
      await device.selectAlternateInterface(bulk.interfaceNumber, bulk.alternateSetting);
    }
    try {
      await device.claimInterface(bulk.interfaceNumber);
    } catch (error) {
      const message = error instanceof Error ? error.message : String(error);
      throw new Error(
        `${message} If Chrome OS claimed the printer, remove it under `
          + 'Settings → Printers so this extension can use the USB interface.',
      );
    }

    try {
      let offset = 0;
      while (offset < payload.length) {
        const length = Math.min(CHUNK_SIZE, payload.length - offset);
        const chunk = payload.subarray(offset, offset + length);
        const result = await device.transferOut(bulk.endpointNumber, chunk);
        if (!result || result.status !== 'ok') {
          throw new Error(`USB bulk transfer failed at byte ${offset}.`);
        }
        const written = Number(result.bytesWritten);
        offset += written > 0 ? written : length;
      }
    } finally {
      try {
        await device.releaseInterface(bulk.interfaceNumber);
      } catch {
        // Best-effort release.
      }
    }
  } finally {
    try {
      await device.close();
    } catch {
      // Best-effort close.
    }
  }
}
