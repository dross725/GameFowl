import { Buffer } from 'buffer';
import type { PrintJobPayload, Session } from './types';

function authHeaders(token: string): Record<string, string> {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
}

export async function loginCompanion(params: {
  serverUrl: string;
  username: string;
  password: string;
  deviceId: string;
  platform: 'android' | 'ios';
  printerName?: string;
  printerAddress?: string;
}): Promise<{ token: string; user: string }> {
  const url = `${params.serverUrl}/api/print-devices/login/`;
  let response: Response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        username: params.username,
        password: params.password,
        device_id: params.deviceId,
        platform: params.platform,
        printer_name: params.printerName || '',
        printer_address: params.printerAddress || '',
      }),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot reach ${url} (${detail}). Use your PC LAN IP, e.g. http://192.168.1.6:8000 — keep http:// and :8000.`,
    );
  }
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Login failed (${response.status})`);
  }
  return { token: data.token, user: data.user };
}

export async function registerPrinter(
  session: Session,
  printerName: string,
  printerAddress: string,
): Promise<void> {
  const response = await fetch(`${session.serverUrl}/api/print-devices/register/`, {
    method: 'POST',
    headers: authHeaders(session.token),
    body: JSON.stringify({
      printer_name: printerName,
      printer_address: printerAddress,
    }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Register failed (${response.status})`);
  }
}

export async function fetchPendingJobs(session: Session): Promise<PrintJobPayload[]> {
  const response = await fetch(`${session.serverUrl}/api/print-jobs/pending/?limit=5`, {
    method: 'GET',
    headers: authHeaders(session.token),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Pending jobs failed (${response.status})`);
  }
  return Array.isArray(data.jobs) ? data.jobs : [];
}

export async function ackJob(
  session: Session,
  jobId: number,
  status: 'printed' | 'failed',
  errorText?: string,
): Promise<void> {
  const response = await fetch(`${session.serverUrl}/api/print-jobs/${jobId}/ack/`, {
    method: 'POST',
    headers: authHeaders(session.token),
    body: JSON.stringify({ status, error: errorText || '' }),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Ack failed (${response.status})`);
  }
}

export async function healthCheck(session: Session): Promise<{ pending_jobs: number }> {
  const response = await fetch(`${session.serverUrl}/api/print-devices/health/`, {
    method: 'GET',
    headers: authHeaders(session.token),
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Health failed (${response.status})`);
  }
  return { pending_jobs: Number(data.pending_jobs || 0) };
}

export function wsPrintJobsUrl(session: Session): string {
  const base = session.serverUrl.replace(/^http/, 'ws');
  return `${base}/ws/print-jobs/?token=${encodeURIComponent(session.token)}`;
}

export function decodeEscposBase64(value: string): Uint8Array {
  return new Uint8Array(Buffer.from(value, 'base64'));
}

/** Minimal ESC/POS test slip for printer pairing checks. */
export function buildTestEscposBytes(): Uint8Array {
  const lines = [
    '\x1b@',
    '\x1ba\x01',
    '\x1bE\x01',
    'PRINTER TEST\n',
    '\x1bE\x00',
    'SmartWagers Print\n',
    'Companion OK\n',
    '\n\n',
    '\x1dV\x42\x00',
  ];
  return new Uint8Array(Buffer.from(lines.join(''), 'binary'));
}
