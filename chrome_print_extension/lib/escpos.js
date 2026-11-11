/** Minimal ESC/POS helpers for the Chromebook USB companion. */

export function decodeEscposBase64(value) {
  const binary = atob(String(value || ''));
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

/** Local pairing slip — no server job. */
export function buildTestEscposBytes() {
  const lines = [
    '\x1b@',
    '\x1ba\x01',
    '\x1bE\x01',
    'PRINTER TEST\n',
    '\x1bE\x00',
    'SmartWagers Print\n',
    'Chrome OS USB OK\n',
    '\n\n\n\n',
    '\x1dV\x42\x04',
  ];
  const text = lines.join('');
  const bytes = new Uint8Array(text.length);
  for (let i = 0; i < text.length; i += 1) {
    bytes[i] = text.charCodeAt(i) & 0xff;
  }
  return bytes;
}
