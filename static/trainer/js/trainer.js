// Card selection and scoring, ported from app/trainer.py.
//
// A card's weight leans on how often you get it wrong and how slow you are
// relative to your own recent baseline -- an absolute speed target would
// punish whoever happens to have a fast keyboard. A card that is hopeless
// gets pulled back after a couple of repeats in a row so one bad bind cannot
// eat a session.
//
// Records are attempts, identified by their bind name (HOTBAR_1_3), because
// the browser no longer has server-side hotkey row ids.

// Latency a session falls back on before there is any history to compare to.
export const DEFAULT_BASELINE_MS = 700.0;

// Miss reasons, most specific first.
export const OK = 'OK';
export const WRONG_KEY = 'WRONG_KEY';
export const MISSING_MOD = 'MISSING_MOD';
export const EXTRA_MOD = 'EXTRA_MOD';
export const TIMEOUT = 'TIMEOUT';

export const MISSEES = new Set([WRONG_KEY, MISSING_MOD, EXTRA_MOD, TIMEOUT]);

/** Why an attempt was wrong, or OK. */
export function classify(expectedCode, expectedMods, code, mods) {
  if (code === null || code === undefined) return TIMEOUT;
  if (code !== expectedCode) return WRONG_KEY;
  const want = new Set(expectedMods);
  const got = new Set(mods);
  if ([...want].some((m) => !got.has(m))) return MISSING_MOD;
  if ([...got].some((m) => !want.has(m))) return EXTRA_MOD;
  return OK;
}

function latencyList(attempts, correctOnly) {
  return attempts
    .filter((a) => (!correctOnly || a.correct) && a.latency_ms !== null && a.latency_ms !== undefined)
    .map((a) => a.latency_ms)
    .sort((a, b) => a - b);
}

export function median(values) {
  if (!values.length) return null;
  const mid = Math.floor(values.length / 2);
  return values.length % 2 ? values[mid] : (values[mid - 1] + values[mid]) / 2;
}

/** Median latency over all correct attempts in a pool. */
export function baseline(attempts) {
  const values = latencyList(attempts, true);
  if (!values.length) return DEFAULT_BASELINE_MS;
  return Math.max(150.0, median(values));
}

/** Lifetime per-card counters, used for weighting and for the scorecard. */
export function statsFor(attempts) {
  const stats = new Map();
  for (const attempt of attempts) {
    const stat = stats.get(attempt.bind) ?? {
      attempts: 0,
      errors: 0,
      correct: 0,
      avg_latency: null,
    };
    stat.attempts += 1;
    if (attempt.correct) {
      stat.correct += 1;
      if (attempt.latency_ms !== null && attempt.latency_ms !== undefined) {
        // Running mean over correct attempts, matching the SQL the PoC used.
        stat.avg_latency =
          stat.avg_latency === null
            ? attempt.latency_ms
            : stat.avg_latency + (attempt.latency_ms - stat.avg_latency) / stat.correct;
      }
    } else {
      stat.errors += 1;
    }
    stats.set(attempt.bind, stat);
  }
  return stats;
}

/** Add server-side counters to local ones; average latencies weighted. */
export function mergeStats(local, remote) {
  const out = new Map(local);
  for (const [bind, other] of Object.entries(remote ?? {})) {
    const mine = out.get(bind);
    if (!mine) {
      out.set(bind, { ...other });
      continue;
    }
    const attempts = mine.attempts + (other.attempts ?? 0);
    const errors = mine.errors + (other.errors ?? 0);
    const correct = (mine.correct ?? 0) + (other.correct ?? 0);
    let avg = null;
    if (correct > 0) {
      const mineCorrect = mine.correct ?? 0;
      const otherCorrect = other.correct ?? 0;
      const mineAvg = mine.avg_latency ?? 0;
      const otherAvg = other.avg_latency ?? 0;
      avg = (mineAvg * mineCorrect + otherAvg * otherCorrect) / correct;
    }
    out.set(bind, { attempts, errors, correct, avg_latency: avg });
  }
  return out;
}

export function weight(stat, baseMs, streak) {
  const attempts = stat?.attempts ?? 0;
  const errors = stat?.errors ?? 0;

  // Shrink towards 0.25 for cards with little history, so a first sighting is
  // neither favoured nor punished much.
  const missRate = (errors + 1.0) / (attempts + 4.0);

  const avg = stat?.avg_latency ?? baseMs;
  const slow = Math.max(0.0, Math.min(2.0, avg / baseMs - 1.0));

  let w = 1.0 + 5.0 * missRate + 2.5 * slow;
  if (streak >= 2) w *= 0.2 ** (streak - 1);
  return w;
}

/**
 * Choose the next card, weighted toward whatever is going worst.
 *
 * `binds` is the parsed KEYBIND list. `allow` is the set of bind names on the
 * chosen job's ticked bars; an explicit empty set means nothing is drilled,
 * not "no filter".
 */
export function pick(binds, options = {}) {
  const {
    stats = new Map(),
    baseMs = DEFAULT_BASELINE_MS,
    streaks = new Map(),
    allow = null,
    exclude = new Set(),
    rng = Math.random,
  } = options;

  const rows = binds.filter((b) => b.code !== null && b.code !== undefined && b.trainable !== false);
  const pool = allow === null ? rows : rows.filter((b) => allow.has(b.name));
  let candidates = pool.filter((b) => !exclude.has(b.name));
  if (!candidates.length) candidates = pool;
  if (!candidates.length) throw new Error('no enabled, trainable binds');

  const weights = candidates.map((b) =>
    weight(stats.get(b.name), baseMs, streaks.get(b.name) ?? 0),
  );
  const total = weights.reduce((a, b) => a + b, 0);
  let roll = rng() * total;
  for (let i = 0; i < candidates.length; i += 1) {
    roll -= weights[i];
    if (roll < 0) return candidates[i];
  }
  return candidates[candidates.length - 1];
}

/** Everything the end-of-session panel shows. */
export function scorecard(attempts) {
  const n = attempts.length;
  const right = attempts.filter((a) => a.correct).length;
  const latencies = latencyList(attempts, false);

  const reasons = {};
  for (const attempt of attempts) reasons[attempt.reason] = (reasons[attempt.reason] ?? 0) + 1;

  const grouped = new Map();
  for (const attempt of attempts) {
    const row = grouped.get(attempt.bind) ?? {
      bind: attempt.bind,
      name: attempt.name ?? attempt.bind,
      label: attempt.label ?? attempt.bind,
      n: 0,
      errors: 0,
      latencies: [],
    };
    row.n += 1;
    if (!attempt.correct) row.errors += 1;
    if (attempt.latency_ms !== null && attempt.latency_ms !== undefined) {
      row.latencies.push(attempt.latency_ms);
    }
    grouped.set(attempt.bind, row);
  }

  const worst = [...grouped.values()]
    .filter((row) => row.n > 0 && (row.errors > 0 || row.n >= 2))
    .map((row) => ({
      bind: row.bind,
      name: row.name,
      label: row.label,
      n: row.n,
      errors: row.errors,
      avg_latency: row.latencies.length
        ? row.latencies.reduce((a, b) => a + b, 0) / row.latencies.length
        : null,
    }))
    .sort(
      (a, b) =>
        b.errors / b.n - a.errors / a.n || (b.avg_latency ?? 0) - (a.avg_latency ?? 0),
    )
    .slice(0, 5);

  return {
    attempts: n,
    correct: right,
    accuracy: n ? right / n : 0.0,
    avg_latency_ms: latencies.length
      ? latencies.reduce((a, b) => a + b, 0) / latencies.length
      : null,
    median_latency_ms: median(latencies),
    p90_latency_ms: latencies.length
      ? latencies[Math.min(latencies.length - 1, Math.floor(latencies.length * 0.9))]
      : null,
    reasons,
    worst,
  };
}
