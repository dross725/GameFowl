const DEFAULTS = {
  serverUrl: '',
  token: '',
  username: '',
  deviceId: '',
  printer: null,
  statusMessage: '',
};

export async function loadState() {
  const stored = await chrome.storage.local.get(Object.keys(DEFAULTS));
  return { ...DEFAULTS, ...stored };
}

export async function saveState(partial) {
  await chrome.storage.local.set(partial);
}

export async function ensureDeviceId() {
  const state = await loadState();
  if (state.deviceId) return state.deviceId;
  const deviceId = `chromeos-${crypto.randomUUID()}`;
  await saveState({ deviceId });
  return deviceId;
}

export async function clearSession() {
  await saveState({
    token: '',
    username: '',
    statusMessage: 'Signed out.',
  });
}
