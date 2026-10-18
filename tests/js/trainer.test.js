import test from 'node:test';
import assert from 'node:assert/strict';

import {
  DEFAULT_BASELINE_MS,
  EXTRA_MOD,
  MISSING_MOD,
  OK,
  TIMEOUT,
  WRONG_KEY,
  baseline,
  classify,
  mergeStats,
  pick,
  scorecard,
  statsFor,
  weight,
} from '../../static/trainer/js/trainer.js';

test('classify separates the ways to get it wrong', () => {
  const cases = [
    [['SHIFT', 'ALT'], 'KeyG', OK],
    [['SHIFT'], 'KeyG', MISSING_MOD],
    [[], 'KeyG', MISSING_MOD],
    [['CTRL', 'SHIFT', 'ALT'], 'KeyG', EXTRA_MOD],
    [['SHIFT', 'ALT'], 'KeyF', WRONG_KEY],
    [[], null, TIMEOUT],
  ];
  for (const [mods, code, want] of cases) {
    assert.equal(classify('KeyG', ['SHIFT', 'ALT'], code, mods), want);
  }
});

test('modifier order does not matter', () => {
  assert.equal(classify('KeyG', ['SHIFT', 'ALT'], 'KeyG', ['ALT', 'SHIFT']), OK);
});

test('a card with little history sits near the fresh baseline', () => {
  const fresh = weight({ attempts: 0, errors: 0, avg_latency: null }, 700.0, 0);
  const oneGood = weight({ attempts: 1, errors: 0, avg_latency: 400 }, 700.0, 0);
  const manyGood = weight({ attempts: 20, errors: 0, avg_latency: 400 }, 700.0, 0);
  assert.ok(manyGood < oneGood && oneGood < fresh);
});

test('heavy miss rate raises the weight', () => {
  const clean = { attempts: 20, errors: 0, avg_latency: 400 };
  const shaky = { attempts: 20, errors: 10, avg_latency: 400 };
  assert.ok(weight(shaky, 700.0, 0) > weight(clean, 700.0, 0));
});

test('slow relative to your own baseline raises the weight', () => {
  const fast = { attempts: 20, errors: 0, avg_latency: 400 };
  const slow = { attempts: 20, errors: 0, avg_latency: 1100 };
  assert.ok(weight(slow, 700.0, 0) > weight(fast, 700.0, 0));
});

test('repeated draws are pulled back', () => {
  const stat = { attempts: 10, errors: 10, avg_latency: 2000 };
  assert.ok(weight(stat, 700.0, 4) < weight(stat, 700.0, 0));
});

test('baseline is the median of correct attempts', () => {
  const attempts = [
    { correct: true, latency_ms: 100 },
    { correct: true, latency_ms: 300 },
    { correct: true, latency_ms: 900 },
    { correct: false, latency_ms: 5000 },
  ];
  assert.equal(baseline(attempts), 300);
  assert.equal(baseline([]), DEFAULT_BASELINE_MS);
});

test('stats average latency over correct attempts only', () => {
  const stats = statsFor([
    { bind: 'HOTBAR_1_1', correct: true, latency_ms: 100 },
    { bind: 'HOTBAR_1_1', correct: true, latency_ms: 300 },
    { bind: 'HOTBAR_1_1', correct: false, latency_ms: 9000 },
  ]);
  assert.deepEqual(stats.get('HOTBAR_1_1'), {
    attempts: 3,
    errors: 1,
    correct: 2,
    avg_latency: 200,
  });
});

test('mergeStats adds remote counters to local ones', () => {
  const local = new Map([
    ['HOTBAR_1_1', { attempts: 2, errors: 1, correct: 1, avg_latency: 200 }],
  ]);
  const merged = mergeStats(local, {
    HOTBAR_1_1: { attempts: 2, errors: 0, correct: 2, avg_latency: 400 },
  });
  assert.deepEqual(merged.get('HOTBAR_1_1'), {
    attempts: 4,
    errors: 1,
    correct: 3,
    avg_latency: (200 * 1 + 400 * 2) / 3,
  });
});

test('pick only draws from the ticked bars', () => {
  const binds = [
    { name: 'HOTBAR_1_1', code: 'Digit1', trainable: true },
    { name: 'HOTBAR_1_2', code: 'Digit2', trainable: true },
    { name: 'HOTBAR_2_1', code: 'Digit3', trainable: true },
  ];
  const allow = new Set(['HOTBAR_2_1']);
  for (let i = 0; i < 20; i += 1) {
    assert.equal(pick(binds, { allow }).name, 'HOTBAR_2_1');
  }
});

test('pick refuses when every bar is unticked', () => {
  const binds = [{ name: 'HOTBAR_1_1', code: 'Digit1', trainable: true }];
  assert.throws(() => pick(binds, { allow: new Set() }), /no enabled, trainable binds/);
});

test('pick skips untrainable binds', () => {
  const binds = [
    { name: 'HOTBAR_1_1', code: null, trainable: false },
    { name: 'HOTBAR_1_2', code: 'Digit2', trainable: true },
  ];
  assert.equal(pick(binds).name, 'HOTBAR_1_2');
});

test('scorecard names the worst cards', () => {
  const card = scorecard([
    { bind: 'HOTBAR_1_1', name: 'Adloquium', label: 'Bar 1 · slot 1', correct: true, reason: OK, latency_ms: 200 },
    { bind: 'HOTBAR_1_2', name: 'Succor', label: 'Bar 1 · slot 2', correct: false, reason: WRONG_KEY, latency_ms: 300 },
    { bind: 'HOTBAR_1_2', name: 'Succor', label: 'Bar 1 · slot 2', correct: true, reason: OK, latency_ms: 500 },
    { bind: 'HOTBAR_1_3', name: 'Physick', label: 'Bar 1 · slot 3', correct: false, reason: TIMEOUT, latency_ms: null },
  ]);
  assert.equal(card.attempts, 4);
  assert.equal(card.correct, 2);
  assert.equal(card.accuracy, 0.5);
  assert.equal(card.reasons.WRONG_KEY, 1);
  assert.equal(card.worst[0].bind, 'HOTBAR_1_3');
  assert.equal(card.worst[0].errors, 1);
});
