// Browser storage for the trainer.
//
// Nothing here leaves the machine. The account sync in app.js is a separate,
// explicit step: these keys are the working copy either way.

const PREFIX = 'ffxivtrainer.';

const KEYS = {
  keybind: 'keybind', // {name, b64}
  hotbar: 'hotbar', // {name, b64}
  selection: 'selection', // {job: [bar, ...]}
  order: 'order', // {job: [bar, ...]} in display order
  taught: 'taught', // {bind: event.code}
  job: 'job', // number
  sessions: 'sessions', // finished sessions, unsynced ones included
  lastCard: 'lastCard', // scorecard of the last session
  remoteStats: 'remoteStats', // aggregate counters loaded from the account
  remoteBaseline: 'remoteBaseline',
  remoteSavedAt: 'remoteSavedAt',
};

// Keep the local history bounded: localStorage is only ~5 MB and a session
// with a few hundred attempts is a few tens of KB.
const MAX_SESSIONS = 200;

export function readJSON(key, fallback = null) {
  try {
    const raw = localStorage.getItem(PREFIX + key);
    if (raw === null) return fallback;
    return JSON.parse(raw);
  } catch {
    return fallback;
  }
}

export function writeJSON(key, value) {
  try {
    localStorage.setItem(PREFIX + key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function readFile(key) {
  const stored = readJSON(key, null);
  if (!stored || !stored.b64) return null;
  try {
    return { name: stored.name || key, bytes: base64ToBytes(stored.b64) };
  } catch {
    return null;
  }
}

export function writeFile(key, name, bytes) {
  return writeJSON(key, { name, b64: bytesToBase64(bytes) });
}

export function readSessions() {
  const sessions = readJSON(KEYS.sessions, []);
  return Array.isArray(sessions) ? sessions : [];
}

export function writeSessions(sessions) {
  return writeJSON(KEYS.sessions, sessions.slice(-MAX_SESSIONS));
}

export function bytesToBase64(bytes) {
  let binary = '';
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    binary += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(binary);
}

export function base64ToBytes(b64) {
  const binary = atob(b64);
  const out = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) out[i] = binary.charCodeAt(i);
  return out;
}

export { KEYS };
