// The trainer UI. Files are parsed here; the server only serves static data,
// proxies icons, and stores an optional account copy when you press save.

import { describe } from './keys.js';
import { KeybindError, parseTrainable as parseKeybind } from './keybind_dat.js';
import { parse as parseHotbar } from './hotbar_dat.js';
import * as catalog from './catalog.js';
import * as trainer from './trainer.js';
import * as store from './storage.js';

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const MOD_CODES = {
  ShiftLeft: 'SHIFT', ShiftRight: 'SHIFT',
  ControlLeft: 'CTRL', ControlRight: 'CTRL',
  AltLeft: 'ALT', AltRight: 'ALT',
};

const REASON_TEXT = {
  OK: 'ok', WRONG_KEY: 'wrong key', MISSING_MOD: 'missing modifier',
  EXTRA_MOD: 'extra modifier', TIMEOUT: 'timed out',
};

const CARD_TIMEOUT_MS = 3000;
const DATA_BASE = '/static/trainer/data';

const ROUTES = {
  '/trainer/binds': 'layout',
  '/trainer/hotbars': 'hotbars',
  '/trainer/train': 'session',
  '/trainer/score': 'score',
};
const DEFAULT_PATH = '/trainer/hotbars';

const state = {
  actions: {},
  items: {},
  jobs: [],
  jobList: [],
  keybind: null, // {name, bytes}
  hotbar: null, // {name, bytes}
  binds: [],
  blocks: null,
  combos: new Map(),
  selection: store.readJSON(store.KEYS.selection, {}) ?? {},
  order: store.readJSON(store.KEYS.order, {}) ?? {},
  taught: store.readJSON(store.KEYS.taught, {}) ?? {},
  sessions: store.readSessions(),
  lastCard: store.readJSON(store.KEYS.lastCard, null),
  remoteStats: store.readJSON(store.KEYS.remoteStats, {}) ?? {},
  remoteBaseline: store.readJSON(store.KEYS.remoteBaseline, null),
  remoteSavedAt: store.readJSON(store.KEYS.remoteSavedAt, null),
  selectedJob: null,
  hotbarsData: null,
  barChoice: null,
  session: null, // {id, jobId, startedAt, durationS, attempts, answered, card, correct}
  cardShownAt: 0,
  awaitingCorrect: false,
  timer: null,
  timeoutTimer: null,
  teaching: null,
  user: null,
  syncing: false,
};

// ------------------------------------------------------------------ api

async function fetchJson(url, opts) {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = body.error || body.detail || detail;
    } catch {
      // not JSON; keep the status text
    }
    throw new Error(detail);
  }
  return res.json();
}

// ----------------------------------------------------------------- views

function showView(name) {
  for (const view of $$('.view')) view.hidden = view.id !== `view-${name}`;
  for (const btn of $$('.nav-btn')) btn.classList.toggle('active', btn.dataset.view === name);
}

function routeFromPath() {
  let name = ROUTES[location.pathname];
  if (!name) {
    history.replaceState(null, '', DEFAULT_PATH);
    name = ROUTES[DEFAULT_PATH];
  }
  if (name !== 'session') finishSession();
  showView(name);
  if (name === 'session') showIdleSession();
  if (name === 'hotbars') openHotbars();
  if (name === 'score') refreshScore();
}

function navigate(path) {
  if (state.session && ROUTES[path] !== 'session') finishSession();
  history.pushState(null, '', path);
  routeFromPath();
}

document.addEventListener('click', (ev) => {
  const link = ev.target.closest('a.nav-btn');
  if (!link || ev.defaultPrevented || ev.button !== 0) return;
  if (ev.metaKey || ev.ctrlKey || ev.shiftKey || ev.altKey) return;
  const path = link.getAttribute('href');
  if (!ROUTES[path] || path === location.pathname) return;
  ev.preventDefault();
  navigate(path);
});

window.addEventListener('popstate', routeFromPath);

// ---------------------------------------------------------------- data

async function loadIndices() {
  try {
    const [actions, items, jobs] = await Promise.all([
      fetchJson(`${DATA_BASE}/action_index.json`),
      fetchJson(`${DATA_BASE}/item_index.json`),
      fetchJson(`${DATA_BASE}/job_index.json`),
    ]);
    state.actions = actions ?? {};
    state.items = items ?? {};
    state.jobs = jobs ?? [];
  } catch (err) {
    setImportStatus(`could not load the bundled game data: ${err.message}`, true);
  }
}

function applyTaught() {
  for (const bind of state.binds) {
    const taught = state.taught[bind.name];
    if (taught) {
      bind.code = taught;
      // A taught key makes an otherwise unknown bind trainable. A second held
      // key we cannot name still blocks it: guessing would accept every miss.
      bind.trainable = bind.unmappedMod === 0;
    }
  }
}

function setKeybind(bytes, name, persist = true) {
  const binds = parseKeybind(bytes);
  if (!binds.length) throw new KeybindError('no bound keys found in that file');
  state.keybind = { name, bytes };
  if (persist && !store.writeFile(store.KEYS.keybind, name, bytes)) {
    setImportStatus(
      'KEYBIND.DAT is too large for browser storage; sign in to save it to your account',
      true,
    );
  }
  state.binds = binds;
  applyTaught();
  state.combos = catalog.combosFor(state.binds);
  refreshBinds();
}

function setHotbar(bytes, name, persist = true) {
  const blocks = parseHotbar(bytes);
  if (!blocks.size) throw new Error('no blocks found in that HOTBAR.DAT');
  state.hotbar = { name, bytes };
  if (persist && !store.writeFile(store.KEYS.hotbar, name, bytes)) {
    setImportStatus(
      'HOTBAR.DAT is too large for browser storage; sign in to save it to your account',
      true,
    );
  }
  state.blocks = blocks;
  state.hotbarsData = null;
}

function comboFor(bind) {
  return describe(bind.mods, bind.keyId, bind.code);
}

// ---------------------------------------------------------------- hotbars

function loadJobs() {
  state.jobList = catalog.jobList(state.blocks, state.jobs);
  const sel = $('#job-select');
  sel.textContent = '';
  for (const [label, group] of [
    ['Jobs', state.jobList.filter((j) => j.named)],
    ['Unnamed blocks', state.jobList.filter((j) => !j.named)],
  ]) {
    if (!group.length) continue;
    const og = document.createElement('optgroup');
    og.label = label;
    for (const job of group) {
      const opt = document.createElement('option');
      opt.value = String(job.block);
      opt.textContent = job.abbreviation;
      if (job.named) opt.title = job.name;
      og.appendChild(opt);
    }
    sel.appendChild(og);
  }
  sel.disabled = !state.jobList.length;
  return state.jobList.length > 0;
}

function pickJob(preferred) {
  if (!loadJobs()) return false;
  const wanted = Number(preferred ?? 0);
  const found =
    state.jobList.find((j) => j.block === wanted) ||
    state.jobList.find((j) => j.named) ||
    state.jobList[0];
  state.selectedJob = found.block;
  $('#job-select').value = String(found.block);
  return true;
}

function chosenBarsFor(job, bars) {
  const stored = state.selection[String(job)];
  if (Array.isArray(stored)) return new Set(stored.map(Number));
  return new Set(bars.filter((b) => b.binds > 0).map((b) => b.bar));
}

function barsFor(job) {
  return catalog.barsFor(job, {
    blocks: state.blocks,
    combos: state.combos,
    actions: state.actions,
    items: state.items,
    jobs: state.jobs,
  });
}

function orderedBars(job) {
  const bars = state.hotbarsData?.bars ?? [];
  const order = state.order[String(job)];
  if (!Array.isArray(order)) return bars.slice();
  const rank = new Map(order.map((bar, index) => [Number(bar), index]));
  return bars.slice().sort((a, b) => (rank.get(a.bar) ?? 999) - (rank.get(b.bar) ?? 999));
}

function renderHotbars() {
  const body = $('#hotbar-body');
  body.textContent = '';
  if (!state.hotbarsData || !state.hotbarsData.available) return;

  const job = state.hotbarsData.job.id;
  const bars = orderedBars(job);
  if (!state.barChoice) state.barChoice = chosenBarsFor(job, bars);

  for (const bar of bars) {
    const row = document.createElement('div');
    const on = bar.binds > 0 && state.barChoice.has(bar.bar);
    row.className = 'hb-row' + (on ? '' : ' hb-off');

    const index = bars.indexOf(bar);

    const toggle = document.createElement('input');
    toggle.type = 'checkbox';
    toggle.checked = on;
    toggle.disabled = bar.binds === 0;
    toggle.className = 'hb-check';
    toggle.addEventListener('change', () => {
      if (toggle.checked) state.barChoice.add(bar.bar);
      else state.barChoice.delete(bar.bar);
      row.classList.toggle('hb-off', !toggle.checked);
      state.selection[String(job)] = [...state.barChoice];
      store.writeJSON(store.KEYS.selection, state.selection);
    });
    row.appendChild(toggle);

    const num = document.createElement('span');
    num.className = 'hb-bar-num';
    num.textContent = String(bar.bar);
    row.appendChild(num);

    const tiles = document.createElement('div');
    tiles.className = 'hb-tiles';
    for (const slot of bar.slots) tiles.appendChild(hotbarTile(slot));
    row.appendChild(tiles);

    const controls = document.createElement('span');
    controls.className = 'hb-move';
    for (const [glyph, delta] of [['\u25b2', -1], ['\u25bc', 1]]) {
      const button = document.createElement('button');
      button.type = 'button';
      button.className = 'hb-move-btn';
      button.textContent = glyph;
      button.addEventListener('click', () => {
        const target = index + delta;
        if (target < 0 || target >= bars.length) return;
        [bars[index], bars[target]] = [bars[target], bars[index]];
        state.order[String(job)] = bars.map((b) => b.bar);
        store.writeJSON(store.KEYS.order, state.order);
        renderHotbars();
      });
      controls.appendChild(button);
    }
    row.appendChild(controls);
    body.appendChild(row);
  }
}

function hotbarTile(slot) {
  const box = document.createElement('div');
  box.className = 'hb-tile';
  box.title = [slot.bind, slot.name, slot.key].filter(Boolean).join(' · ');

  const key = document.createElement('span');
  key.className = 'hb-key';
  if (slot.key) {
    shortKeyParts(slot.key).forEach((part, i) => {
      if (i) {
        key.appendChild(document.createTextNode('+'));
        key.appendChild(document.createElement('wbr'));
      }
      key.appendChild(document.createTextNode(part));
    });
  }
  box.appendChild(key);

  if (slot.icon) {
    const icon = document.createElement('img');
    icon.className = 'hb-icon';
    icon.loading = 'lazy';
    icon.alt = '';
    icon.src = slot.icon;
    icon.addEventListener('error', () => {
      icon.classList.add('hb-icon-unknown');
      icon.removeAttribute('src');
    });
    box.appendChild(icon);
  } else {
    const placeholder = document.createElement('span');
    placeholder.className = 'hb-icon ' + (slot.action ? 'hb-icon-unknown' : 'hb-icon-blank');
    box.appendChild(placeholder);
  }

  const label = document.createElement('span');
  label.className = 'hb-name';
  label.textContent = slot.name || '';
  box.appendChild(label);
  return box;
}

async function loadHotbars(job) {
  const status = $('#hotbar-status');
  if (job === null || job === undefined) return;
  const data = barsFor(job);
  if (!data.available) {
    state.hotbarsData = null;
    status.textContent = data.reason || 'no HOTBAR.DAT';
    $('#job-note').textContent = '';
    $('#hotbar-body').textContent = '';
    return;
  }
  state.hotbarsData = data;
  state.barChoice = null;
  state.barChoice = chosenBarsFor(job, data.bars);
  status.textContent = `${data.job.abbreviation} · ${data.job.name}`;
  const bound = data.bars.reduce((a, b) => a + b.binds, 0);
  const barsWithKeys = data.bars.filter((b) => b.binds > 0).length;
  $('#job-note').textContent = `${bound} key${bound === 1 ? '' : 's'} bound across ${barsWithKeys} bars`;
  renderHotbars();
}

async function openHotbars() {
  await ready;
  if (!state.jobList.length) {
    $('#hotbar-status').textContent = 'no HOTBAR.DAT. Upload one on the Binds tab.';
    return;
  }
  await loadHotbars(state.selectedJob);
}

$('#job-select').addEventListener('change', (ev) => {
  state.selectedJob = Number(ev.target.value);
  store.writeJSON(store.KEYS.job, state.selectedJob);
  loadHotbars(state.selectedJob);
});

// ---------------------------------------------------------------- import

$('#file-input').addEventListener('change', async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  setImportStatus(`reading ${file.name}…`);
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    setKeybind(bytes, file.name);
    setImportStatus(`imported ${state.binds.length} binds from ${file.name}`);
    if (state.blocks) await loadHotbars(state.selectedJob);
  } catch (err) {
    setImportStatus(err.message, true);
  }
  ev.target.value = '';
});

$('#file-input-bar').addEventListener('change', async (ev) => {
  const file = ev.target.files[0];
  if (!file) return;
  setImportStatus(`reading ${file.name}…`);
  try {
    const bytes = new Uint8Array(await file.arrayBuffer());
    setHotbar(bytes, file.name);
    setImportStatus(`read ${state.blocks.size} hotbar blocks from ${file.name}`);
    if (await pickJob(state.selectedJob)) await loadHotbars(state.selectedJob);
  } catch (err) {
    setImportStatus(err.message, true);
  }
  ev.target.value = '';
});

function setImportStatus(text, isError = false) {
  const el = $('#import-status');
  if (!el) return;
  el.textContent = text;
  el.style.color = isError ? 'var(--bad)' : 'var(--dim)';
}

function refreshBinds() {
  renderBinds();
}

const SLOT_CHARS = '1234567890AB';

// "HOTBAR_2_0" -> { bar: 2, slot: 10 }
function bindPosition(name) {
  const m = /^HOTBAR_(\d+)_([0-9AB])$/.exec(name);
  if (!m) return null;
  return { bar: Number(m[1]), slot: SLOT_CHARS.indexOf(m[2]) + 1 };
}

function comboMarkup(bind) {
  if (!bind.code) return '<span class="unknown">unknown key</span>';
  return comboParts(comboFor(bind)).map((part) => `<kbd>${part}</kbd>`).join(' + ');
}

function startTeaching(name) {
  state.teaching = name;
  $('#binds-status').textContent = 'Press the key this bind uses. Esc cancels.';
  window.focus();
}

// One row per slot, the bar number spanning its own block of rows.
function renderBinds() {
  const tbody = $('#binds-table tbody');
  tbody.textContent = '';

  const rows = state.binds
    .map((bind) => ({ bind, at: bindPosition(bind.name) }))
    .filter((row) => row.at)
    .sort((a, b) => a.at.bar - b.at.bar || a.at.slot - b.at.slot);

  for (let start = 0; start < rows.length;) {
    const bar = rows[start].at.bar;
    let end = start;
    while (end < rows.length && rows[end].at.bar === bar) end += 1;

    for (let i = start; i < end; i += 1) {
      const { bind, at } = rows[i];
      const tr = document.createElement('tr');

      if (i === start) {
        const barCell = document.createElement('td');
        barCell.className = 'bar-cell';
        barCell.rowSpan = end - start;
        barCell.textContent = String(bar);
        tr.appendChild(barCell);
      }

      const slotCell = document.createElement('td');
      slotCell.className = 'slot-cell';
      slotCell.textContent = String(at.slot);
      tr.appendChild(slotCell);

      const comboCell = document.createElement('td');
      comboCell.innerHTML = comboMarkup(bind);
      tr.appendChild(comboCell);

      const actionCell = document.createElement('td');
      if (!bind.code) {
        const button = document.createElement('button');
        button.type = 'button';
        button.textContent = 'teach';
        button.addEventListener('click', () => startTeaching(bind.name));
        actionCell.appendChild(button);
      }
      tr.appendChild(actionCell);
      tbody.appendChild(tr);
    }
    start = end;
  }

  $('#binds-card').hidden = rows.length === 0;
  $('#binds-count').textContent = String(rows.length);
}

// ------------------------------------------------------------- session

function allLocalAttempts() {
  const out = [];
  for (const session of state.sessions) {
    for (const attempt of session.attempts ?? []) out.push(attempt);
  }
  return out;
}

function mergedStats() {
  return trainer.mergeStats(trainer.statsFor(allLocalAttempts()), state.remoteStats);
}

function currentBaseline() {
  const attempts = allLocalAttempts();
  const hasLocal = attempts.some((a) => a.correct && a.latency_ms !== null && a.latency_ms !== undefined);
  if (hasLocal) return trainer.baseline(attempts);
  return state.remoteBaseline ?? trainer.DEFAULT_BASELINE_MS;
}

function allowedBindsFor(job, data) {
  const chosen = chosenBarsFor(job, data.bars);
  const allow = new Set();
  for (const bar of data.bars) {
    if (!chosen.has(bar.bar)) continue;
    for (const slot of bar.slots) {
      if (slot.action) allow.add(slot.bind);
    }
  }
  return allow;
}

function pickCard(job) {
  const data = barsFor(job);
  if (!data.available) throw new Error('upload HOTBAR.DAT on the Binds tab first');
  const allow = allowedBindsFor(job, data);
  const streaks = new Map();
  if (state.session) {
    for (const [bind, count] of state.session.answered) {
      if (count >= 2) streaks.set(bind, count);
    }
  }
  const bind = trainer.pick(state.binds, {
    stats: mergedStats(),
    baseMs: currentBaseline(),
    allow,
    streaks,
  });
  const ability = catalog.lookup(job, bind.name, {
    blocks: state.blocks,
    actions: state.actions,
    items: state.items,
  });
  return {
    bind: bind.name,
    name: ability?.name ?? bind.label,
    label: bind.label,
    code: bind.code,
    mods: bind.mods,
    combo: comboFor(bind),
    ability,
  };
}

function newSessionId() {
  if (globalThis.crypto?.randomUUID) return crypto.randomUUID();
  return `${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

async function startSession() {
  showView('session');
  showIdleSession();
  $('#session-error').textContent = '';

  try {
    if (!state.binds.length) throw new Error('upload KEYBIND.DAT on the Binds tab first');
    if (!state.blocks) throw new Error('upload HOTBAR.DAT on the Binds tab first');
    if (!state.selectedJob) {
      if (!pickJob(store.readJSON(store.KEYS.job, null))) throw new Error('no job to drill');
    }
    const job = state.selectedJob;
    const card = pickCard(job);
    const jobInfo = state.jobList.find((j) => j.block === job);
    state.session = {
      id: newSessionId(),
      jobId: job,
      jobLabel: jobInfo?.abbreviation ?? `B${job}`,
      startedAt: performance.now(),
      startedAtIso: new Date().toISOString(),
      durationS: 30,
      attempts: [],
      answered: new Map(),
      correct: 0,
      card,
    };
    $('#session-idle').hidden = true;
    $('#session-live').hidden = false;
    document.body.classList.add('training');
    drawCard();
    startClock();
  } catch (err) {
    $('#session-error').textContent = err.message;
  }
}

$('#btn-start').addEventListener('click', startSession);

function drawCard() {
  const card = state.session.card;
  state.cardShownAt = performance.now();
  state.awaitingCorrect = false;

  const prompt = $('#prompt');
  const ability = card.ability;
  if (ability) {
    prompt.innerHTML = '';
    if (ability.icon) {
      const icon = document.createElement('img');
      icon.className = 'hud-icon';
      icon.alt = '';
      icon.src = ability.icon;
      icon.addEventListener('error', () => icon.remove());
      prompt.appendChild(icon);
    }
    const name = document.createElement('span');
    name.className = 'hud-name';
    name.textContent = ability.name;
    prompt.appendChild(name);
  } else {
    prompt.textContent = card.label;
  }

  $('#reveal').hidden = true;
  $('#feedback').textContent = '';
  $('#feedback').className = '';
  clearTimeout(state.timeoutTimer);
  state.timeoutTimer = setTimeout(() => recordAttempt(null, []), CARD_TIMEOUT_MS);
}

function startClock() {
  clearInterval(state.timer);
  state.timer = setInterval(() => {
    const left = state.session.durationS - (performance.now() - state.session.startedAt) / 1000;
    $('#hud-time').textContent = Math.max(0, left).toFixed(1);
    if (left <= 0) endSession();
  }, 100);
}

function showIdleSession() {
  if (state.session) return;
  $('#session-idle').hidden = false;
  $('#session-live').hidden = true;
}

function endSession() {
  const card = finishSession();
  if (!card) return;
  navigate('/trainer/score');
  renderScore(card);
}

function finishSession() {
  if (!state.session) return null;
  clearInterval(state.timer);
  clearTimeout(state.timeoutTimer);
  document.body.classList.remove('training');

  const session = state.session;
  const card = trainer.scorecard(session.attempts);
  if (session.attempts.length) {
    state.sessions.push({
      client_id: session.id,
      job_id: session.jobId,
      job_label: session.jobLabel,
      started_at: session.startedAtIso,
      duration_s: session.durationS,
      attempts: session.attempts,
    });
    store.writeSessions(state.sessions);
  }
  state.session = null;
  state.lastCard = card;
  store.writeJSON(store.KEYS.lastCard, card);
  updateAccountStatus();
  return card;
}

function refreshScore() {
  if (state.lastCard) {
    renderScore(state.lastCard);
    return;
  }
  $('#score-body').innerHTML =
    '<p class="hint">No session yet. Finish one and it will show up here.</p>';
}

// ------------------------------------------------------------ keyboard

function pressedModifiers(ev) {
  const mods = [];
  if (ev.shiftKey) mods.push('SHIFT');
  if (ev.ctrlKey) mods.push('CTRL');
  if (ev.altKey) mods.push('ALT');
  return mods;
}

window.addEventListener('keydown', (ev) => {
  // Teaching a key we could not map: any non-modifier key works.
  if (state.teaching !== null) {
    ev.preventDefault();
    if (ev.code === 'Escape') {
      state.teaching = null;
      $('#binds-status').textContent = 'kept as unknown key.';
      return;
    }
    if (!MOD_CODES[ev.code]) {
      const name = state.teaching;
      state.teaching = null;
      state.taught[name] = ev.code;
      store.writeJSON(store.KEYS.taught, state.taught);
      const bind = state.binds.find((b) => b.name === name);
      if (bind) {
        bind.code = ev.code;
        bind.trainable = bind.unmappedMod === 0;
      }
      state.combos = catalog.combosFor(state.binds);
      renderBinds();
      $('#binds-status').textContent = `mapped to ${keyLabel(ev.code)}.`;
      if (state.blocks) loadHotbars(state.selectedJob);
    }
    return;
  }

  if (!state.session) return;
  ev.preventDefault();
  // A synthetic or IME event can arrive without a code. Treat it as no press
  // so the card times out instead of recording a mystery wrong key.
  if (!ev.code || ev.repeat || MOD_CODES[ev.code]) return;
  if (ev.code === 'Escape') {
    endSession();
    return;
  }
  recordAttempt(ev.code, pressedModifiers(ev));
});

function recordAttempt(code, mods) {
  if (!state.session || !state.session.card) return;
  clearTimeout(state.timeoutTimer);

  const card = state.session.card;
  const latency = Math.round(performance.now() - state.cardShownAt);
  const reason = trainer.classify(card.code, card.mods, code, mods);
  const ok = reason === trainer.OK;

  state.session.attempts.push({
    bind: card.bind,
    name: card.ability?.name ?? card.label,
    label: card.label,
    correct: ok,
    reason,
    latency_ms: latency,
    pressed_code: code,
    pressed_mods: mods,
    at: new Date().toISOString(),
  });
  state.session.answered.set(card.bind, (state.session.answered.get(card.bind) ?? 0) + 1);
  if (ok) state.session.correct += 1;

  const feedback = $('#feedback');
  if (ok) {
    feedback.textContent = REASON_TEXT.OK;
    feedback.className = 'ok';
    nextCard();
  } else {
    // Say what was actually pressed, not just that it was wrong.
    feedback.textContent =
      reason === trainer.TIMEOUT
        ? REASON_TEXT.TIMEOUT
        : `${REASON_TEXT[reason]}: pressed ${pressedLabel(code, mods)}`;
    feedback.className = 'bad';
    $('#reveal').innerHTML = `correct combo: ${revealComboMarkup(card)}`;
    $('#reveal').hidden = false;
    state.awaitingCorrect = true; // wait for the right press before moving on
  }
  updateHud();
}

function nextCard() {
  try {
    state.session.card = pickCard(state.session.jobId);
  } catch {
    endSession();
    return;
  }
  drawCard();
}

function updateHud() {
  const session = state.session;
  if (!session) return;
  const acc = session.attempts.length
    ? Math.round((session.correct / session.attempts.length) * 100)
    : 100;
  $('#hud-acc').textContent = `${acc}%`;
  $('#hud-n').textContent = session.attempts.length;
}

// The reveal reuses comboParts but reads the card's precomputed combo.
function revealComboMarkup(card) {
  if (!card.code) return '<span class="unknown">unknown key</span>';
  return comboParts(card.combo).map((part) => `<kbd>${part}</kbd>`).join(' + ');
}

// ---------------------------------------------------------------- score

function renderScore(card) {
  const pct = (v) => `${(v * 100).toFixed(1)}%`;
  const ms = (v) => (v === null || v === undefined ? 'n/a' : `${Math.round(v)} ms`);
  const reasons = Object.entries(card.reasons)
    .filter(([key]) => key !== 'OK')
    .map(([key, n]) => `<span class="tag">${REASON_TEXT[key] || key} ${n}</span>`)
    .join(' ');

  const worst = card.worst.length
    ? `<table class="worst"><thead><tr><th>Card</th><th>Missed</th><th>Mean</th></tr></thead><tbody>
       ${card.worst.map((w) => `<tr>
         <td>${w.name || w.label}</td>
         <td>${w.errors}/${w.n}</td>
         <td>${ms(w.avg_latency)}</td></tr>`).join('')}
       </tbody></table>`
    : '<p class="hint">No misses to single out.</p>';

  $('#score-body').innerHTML = `
    <div class="grid">
      <div class="stat"><div class="v">${card.attempts}</div><div class="k">cards</div></div>
      <div class="stat"><div class="v">${pct(card.accuracy)}</div><div class="k">accuracy</div></div>
      <div class="stat"><div class="v">${ms(card.avg_latency_ms)}</div><div class="k">mean</div></div>
      <div class="stat"><div class="v">${ms(card.median_latency_ms)}</div><div class="k">median</div></div>
      <div class="stat"><div class="v">${ms(card.p90_latency_ms)}</div><div class="k">p90</div></div>
    </div>
    <p class="hint">${reasons || 'clean run'}</p>
    ${worst}`;
}

// ---------------------------------------------------------------- account

async function loadAccount() {
  state.user = null;
  try {
    const res = await fetch('/api/me', { headers: { Accept: 'application/json' } });
    if (res.ok) state.user = await res.json();
  } catch {
    state.user = null;
  }
  renderAccount();
}

function accountButton(label, onClick) {
  const button = document.createElement('button');
  button.type = 'button';
  button.textContent = label;
  button.addEventListener('click', onClick);
  return button;
}

function renderAccount() {
  const box = $('#account');
  box.textContent = '';
  if (!state.user) {
    const link = document.createElement('a');
    link.className = 'login';
    link.href = `/auth/login?next=${encodeURIComponent('/trainer/')}`;
    link.textContent = 'Log in with Discord to save';
    box.appendChild(link);
    return;
  }

  const who = document.createElement('span');
  who.className = 'who';
  who.textContent = state.user.name || state.user.id;
  box.appendChild(who);

  const save = accountButton('Save to account', saveToAccount);
  const load = accountButton('Load from account', loadFromAccount);
  box.appendChild(save);
  box.appendChild(load);

  const logout = document.createElement('a');
  logout.href = '/auth/logout';
  logout.textContent = 'Log out';
  box.appendChild(logout);

  const status = document.createElement('span');
  status.className = 'account-status';
  status.id = 'account-status';
  box.appendChild(status);
  updateAccountStatus();
}

function setAccountStatus(text, kind = '') {
  const el = $('#account-status');
  if (!el) return;
  el.textContent = text;
  el.className = `account-status${kind ? ` ${kind}` : ''}`;
}

function updateAccountStatus() {
  if (!state.user) return;
  const el = $('#account-status');
  if (!el) return;
  if (state.syncing) {
    setAccountStatus('saving…');
    return;
  }
  const unsynced = state.sessions.length;
  if (unsynced) {
    setAccountStatus(`${unsynced} unsynced session${unsynced === 1 ? '' : 's'}`);
  } else if (state.remoteSavedAt) {
    setAccountStatus(`saved ${state.remoteSavedAt}`);
  } else {
    setAccountStatus('nothing saved on this account yet');
  }
}

async function saveToAccount() {
  if (!state.user || state.syncing) return;
  if (!state.keybind && !state.hotbar) {
    setAccountStatus('upload your files before saving', 'bad');
    return;
  }
  state.syncing = true;
  updateAccountStatus();
  try {
    const payload = {
      keybind: state.keybind
        ? { name: state.keybind.name, b64: store.bytesToBase64(state.keybind.bytes) }
        : null,
      hotbar: state.hotbar
        ? { name: state.hotbar.name, b64: store.bytesToBase64(state.hotbar.bytes) }
        : null,
      selection: state.selection,
      order: state.order,
      taught: state.taught,
      job_id: state.selectedJob,
      sessions: state.sessions,
    };
    const data = await fetchJson('/trainer/api/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    state.sessions = [];
    store.writeSessions([]);
    state.remoteStats = data.stats ?? {};
    state.remoteBaseline = data.baseline_ms ?? null;
    state.remoteSavedAt = data.saved_at ?? new Date().toISOString();
    store.writeJSON(store.KEYS.remoteStats, state.remoteStats);
    store.writeJSON(store.KEYS.remoteBaseline, state.remoteBaseline);
    store.writeJSON(store.KEYS.remoteSavedAt, state.remoteSavedAt);
    state.syncing = false;
    updateAccountStatus();
    setAccountStatus(
      `saved ${data.sessions_saved ?? 0} session${(data.sessions_saved ?? 0) === 1 ? '' : 's'}`,
      'good',
    );
  } catch (err) {
    state.syncing = false;
    setAccountStatus(err.message, 'bad');
  }
}

async function loadFromAccount() {
  if (!state.user || state.syncing) return;
  try {
    const data = await fetchJson('/trainer/api/state');
    if (!data.saved) {
      setAccountStatus('nothing saved on this account yet');
      return;
    }
    if (!confirm('Replace the binds and hotbar in this browser with the saved copy?')) return;
    if (data.files?.keybind) {
      setKeybind(
        store.base64ToBytes(data.files.keybind.b64),
        data.files.keybind.name || 'KEYBIND.DAT',
      );
    }
    if (data.files?.hotbar) {
      setHotbar(
        store.base64ToBytes(data.files.hotbar.b64),
        data.files.hotbar.name || 'HOTBAR.DAT',
      );
    }
    state.selection = data.selection ?? {};
    state.order = data.order ?? {};
    state.taught = data.taught ?? {};
    if (Number.isInteger(data.job_id)) {
      state.selectedJob = data.job_id;
      store.writeJSON(store.KEYS.job, state.selectedJob);
    }
    state.remoteStats = data.stats ?? {};
    state.remoteBaseline = data.baseline_ms ?? null;
    state.remoteSavedAt = data.saved_at ?? null;
    store.writeJSON(store.KEYS.selection, state.selection);
    store.writeJSON(store.KEYS.order, state.order);
    store.writeJSON(store.KEYS.taught, state.taught);
    store.writeJSON(store.KEYS.remoteStats, state.remoteStats);
    store.writeJSON(store.KEYS.remoteBaseline, state.remoteBaseline);
    store.writeJSON(store.KEYS.remoteSavedAt, state.remoteSavedAt);

    // Re-apply taught keys to the freshly loaded layout.
    if (state.keybind) {
      setKeybind(state.keybind.bytes, state.keybind.name);
    }
    if (state.blocks) {
      if (await pickJob(state.selectedJob)) await loadHotbars(state.selectedJob);
    }
    if (!state.sessions.length && data.last_session?.attempts?.length) {
      state.lastCard = trainer.scorecard(data.last_session.attempts);
      store.writeJSON(store.KEYS.lastCard, state.lastCard);
    }
    updateAccountStatus();
    setAccountStatus('loaded from your account', 'good');
    routeFromPath();
  } catch (err) {
    setAccountStatus(err.message, 'bad');
  }
}

// ------------------------------------------------------- key formatting

const KEY_LABELS = {
  Space: 'Space', Tab: 'Tab', Enter: 'Enter', Escape: 'Esc', Backspace: 'Backspace',
  CapsLock: 'Caps', NumLock: 'NumLock', ScrollLock: 'ScrLk', Pause: 'Pause',
  PrintScreen: 'PrtSc', Insert: 'Ins', Delete: 'Del', Help: 'Help',
  Home: 'Home', End: 'End', PageUp: 'PgUp', PageDown: 'PgDn',
  ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right',
  MetaLeft: 'Win', MetaRight: 'Win', ContextMenu: 'Menu',
  NumpadMultiply: 'Num*', NumpadAdd: 'Num+', NumpadSubtract: 'Num-',
  NumpadDecimal: 'Num.', NumpadDivide: 'Num/', NumpadComma: 'Num,',
};

const MOD_LABELS = { SHIFT: 'Shift', CTRL: 'Ctrl', ALT: 'Alt' };

function keyLabel(code) {
  if (!code) return 'nothing';
  if (KEY_LABELS[code]) return KEY_LABELS[code];
  const numpad = /^Numpad(\d)$/.exec(code);
  if (numpad) return `Num${numpad[1]}`;
  if (code.startsWith('Key')) return code.slice(3);
  if (code.startsWith('Digit')) return code.slice(5);
  if (/^F\d+$/.test(code)) return code;
  return code;
}

function pressedLabel(code, mods) {
  const parts = (mods || []).map((m) => MOD_LABELS[m] || m);
  if (code) parts.push(keyLabel(code));
  return parts.join('+') || 'nothing';
}

// Split a combo without breaking a key whose label contains a plus: numpad
// plus arrives as "Num+", so a plain split('+') would invent an empty part.
function comboParts(combo) {
  const parts = [];
  let rest = combo;
  for (;;) {
    const mod = ['CTRL', 'ALT', 'SHIFT'].find((m) => rest.startsWith(`${m}+`));
    if (!mod) break;
    parts.push(mod);
    rest = rest.slice(mod.length + 1);
  }
  parts.push(rest);
  return parts;
}

// Tile form of a combo.
function shortKeyParts(combo) {
  return comboParts(combo).map((part) => {
    const named = { SHIFT: '⇧', CTRL: 'Ctrl', ALT: 'Alt', Space: '␣' };
    if (named[part]) return named[part];
    const digit = /^Digit(\d)$/.exec(part);
    if (digit) return digit[1];
    const numpad = /^Num(\d)$/.exec(part);
    if (numpad) return `N${numpad[1]}`;
    const symbols = {
      'Num*': 'N*', 'Num+': 'N+', 'Num-': 'N-', 'Num.': 'N.', 'Num/': 'N/',
      'Num,': 'N,',
    };
    if (symbols[part]) return symbols[part];
    return part.replace(/^Key/, '');
  });
}

// ------------------------------------------------------------------ init

const ready = (async function init() {
  await loadIndices();

  const keybind = store.readFile(store.KEYS.keybind);
  if (keybind) {
    try {
      setKeybind(keybind.bytes, keybind.name, false);
      setImportStatus(`${state.binds.length} binds loaded from this browser`);
    } catch (err) {
      setImportStatus(err.message, true);
    }
  }

  const hotbar = store.readFile(store.KEYS.hotbar);
  if (hotbar) {
    try {
      setHotbar(hotbar.bytes, hotbar.name, false);
    } catch (err) {
      setImportStatus(err.message, true);
    }
  }

  await loadAccount();
  if (await pickJob(store.readJSON(store.KEYS.job, null))) {
    if (state.blocks) await loadHotbars(state.selectedJob);
  } else {
    $('#hotbar-status').textContent = 'no HOTBAR.DAT. Upload one on the Binds tab.';
  }
})();

ready.then(() => routeFromPath());
