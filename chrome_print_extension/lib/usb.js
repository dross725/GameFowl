/**
 * Raw ESC/POS over USB bulk-OUT (same strategy as the Android UsbEscPos module).
 */

const CHUNK_SIZE = 16384;
const TRANSFER_TIMEOUT_MS = 15000;

function usbCall(fn, ...args) {
  return new Promise((resolve, reject) => {
    fn(...args, (result) => {
      const err = chrome.runtime.lastError;
      if (err) {
        reject(new Error(err.message || String(err)));
        return;
      }
      resolve(result);
    });
  });
}

export function printerLabel(device) {
  const name = device.productName || device.manufacturerName || 'USB printer';
  return `${name} (${device.vendorId}:${device.productId})`;
}

export function printerIdentity(device) {
  return {
    vendorId: device.vendorId,
    productId: device.productId,
    productName: device.productName || '',
    manufacturerName: device.manufacturerName || '',
    label: printerLabel(device),
  };
}

/** User-gesture picker (popup button). Empty filters list every attached USB device. */
export async function choosePrinter() {
  const devices = await usbCall(chrome.usb.getUserSelectedDevices.bind(chrome.usb), {
    multiple: false,
    filters: [],
  });
  if (!devices || !devices.length) {
    throw new Error('No USB printer selected.');
  }
  return printerIdentity(devices[0]);
}

async function findDevice(printer) {
  const devices = await usbCall(chrome.usb.getDevices.bind(chrome.usb), {
    filters: [
      {
        vendorId: printer.vendorId,
        productId: printer.productId,
      },
    ],
  });
  if (!devices || !devices.length) {
    throw new Error(
      'USB printer not found. Reconnect it, then Choose printer again.',
    );
  }
  return devices[0];
}

function findBulkOut(interfaces) {
  for (const iface of interfaces || []) {
    for (const endpoint of iface.endpoints || []) {
      if (endpoint.type === 'bulk' && endpoint.direction === 'out') {
        return {
          interfaceNumber: iface.interfaceNumber,
          endpointAddress: endpoint.address,
        };
      }
    }
  }
  return null;
}

/**
 * Claim, write chunked bulk-OUT, release, close.
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
  const interfaces = await usbCall(chrome.usb.listInterfaces.bind(chrome.usb), device);
  const bulk = findBulkOut(interfaces);
  if (!bulk) {
    throw new Error(
      'This USB device has no bulk-OUT printer endpoint. '
        + 'Serial adapters (CH340 and similar) are not supported — use a raw ESC/POS USB printer.',
    );
  }

  const handle = await usbCall(chrome.usb.openDevice.bind(chrome.usb), device);
  try {
    try {
      await usbCall(
        chrome.usb.claimInterface.bind(chrome.usb),
        handle,
        bulk.interfaceNumber,
      );
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
        const result = await usbCall(
          chrome.usb.bulkTransfer.bind(chrome.usb),
          handle,
          {
            direction: 'out',
            endpoint: bulk.endpointAddress,
            data: chunk.buffer.slice(chunk.byteOffset, chunk.byteOffset + chunk.byteLength),
            timeout: TRANSFER_TIMEOUT_MS,
          },
        );
        const written = Number(result && result.bytesTransferred);
        if (!(written > 0)) {
          throw new Error(`USB bulk transfer failed at byte ${offset}.`);
        }
        offset += written;
      }
    } finally {
      try {
        await usbCall(
          chrome.usb.releaseInterface.bind(chrome.usb),
          handle,
          bulk.interfaceNumber,
        );
      } catch {
        // Best-effort release.
      }
    }
  } finally {
    try {
      await usbCall(chrome.usb.closeDevice.bind(chrome.usb), handle);
    } catch {
      // Best-effort close.
    }
  }
}
