function normalizeServerUrl(url) {
  return String(url || '').trim().replace(/\/$/, '');
}

function authHeaders(token) {
  return {
    Authorization: `Bearer ${token}`,
    'Content-Type': 'application/json',
    Accept: 'application/json',
  };
}

async function readJson(response) {
  try {
    return await response.json();
  } catch {
    return {};
  }
}

export async function loginCompanion({
  serverUrl,
  username,
  password,
  deviceId,
  printerName = '',
  printerAddress = '',
}) {
  const base = normalizeServerUrl(serverUrl);
  const url = `${base}/api/print-devices/login/`;
  let response;
  try {
    response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
      body: JSON.stringify({
        username,
        password,
        device_id: deviceId,
        platform: 'chromeos',
        printer_name: printerName,
        printer_address: printerAddress,
      }),
    });
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    throw new Error(
      `Cannot reach ${url} (${detail}). Use the address in this Chromebook's `
        + 'SmartWagers tab, including port 8080. localhost is this Chromebook, not the server.',
    );
  }
  const data = await readJson(response);
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Login failed (${response.status})`);
  }
  return {
    token: data.token,
    user: data.user,
    serverUrl: base,
  };
}

export async function registerPrinter(session, printerName, printerAddress) {
  const response = await fetch(`${session.serverUrl}/api/print-devices/register/`, {
    method: 'POST',
    headers: authHeaders(session.token),
    body: JSON.stringify({
      printer_name: printerName,
      printer_address: printerAddress,
    }),
  });
  const data = await readJson(response);
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Register failed (${response.status})`);
  }
}

export async function fetchPendingJobs(session) {
  const response = await fetch(
    `${session.serverUrl}/api/print-jobs/pending/?limit=5`,
    {
      method: 'GET',
      headers: authHeaders(session.token),
    },
  );
  const data = await readJson(response);
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Pending jobs failed (${response.status})`);
  }
  return Array.isArray(data.jobs) ? data.jobs : [];
}

export async function ackJob(session, jobId, status, errorText = '') {
  const response = await fetch(`${session.serverUrl}/api/print-jobs/${jobId}/ack/`, {
    method: 'POST',
    headers: authHeaders(session.token),
    body: JSON.stringify({ status, error: errorText || '' }),
  });
  const data = await readJson(response);
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Ack failed (${response.status})`);
  }
}

export async function healthCheck(session) {
  const response = await fetch(`${session.serverUrl}/api/print-devices/health/`, {
    method: 'GET',
    headers: authHeaders(session.token),
  });
  const data = await readJson(response);
  if (!response.ok || !data.ok) {
    throw new Error(data.error || `Health failed (${response.status})`);
  }
  return { pending_jobs: Number(data.pending_jobs || 0) };
}

export { normalizeServerUrl };
