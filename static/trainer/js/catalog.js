// Server-side view of a character's hotbars, ported from hotbar_view.py.
//
// Everything the UI needs about hotbars is assembled here in the page, from
// the uploaded files plus the bundled indices. Icons are proxied by the
// server, which caches them on disk.

import {
  BINDABLE_SLOTS,
  bindName,
  barSlots,
  actionAt,
  jobIds,
  extraBlocks,
  parseBindName,
} from './hotbar_dat.js';
import { describe } from './keys.js';

export const VALID_HOTBARS = 10;

//: Items are stored on hotbars as this offset plus the Item row id, so
//: 1049238 is item 49238. No action id reaches this range.
export const ITEM_OFFSET = 1_000_000;

//: The server owns the icon cache; these paths are relative to the same host.
export const ICON_BASE = '/trainer/api';

/** The item behind a hotbar command id, or null if it is an action. */
export function itemFor(actionId, items) {
  // 2,000,000+ values exist in the file too, but what the second offset means
  // is not verified, so they stay unnamed rather than guessed at.
  if (!(actionId >= ITEM_OFFSET && actionId < 2 * ITEM_OFFSET)) return null;
  const baseId = actionId - ITEM_OFFSET;
  const item = items?.[String(baseId)];
  if (!item) return null;
  return {
    base: baseId,
    name: item.name || `item #${baseId}`,
    icon: `${ICON_BASE}/item-icon/${baseId}`,
  };
}

/** Every block that can be trained, named where possible. */
export function jobList(blocks, jobs) {
  if (!blocks) return [];
  const byId = new Map((jobs ?? []).map((j) => [Number(j.id), j]));
  const out = [];
  for (const id of jobIds(blocks)) {
    const info = byId.get(id) ?? {};
    out.push({
      block: id,
      id,
      abbreviation: info.abbreviation ?? `B${id}`,
      name: info.name ?? '',
      named: byId.has(id),
    });
  }
  for (const id of extraBlocks(blocks)) {
    out.push({
      block: id,
      id,
      abbreviation: `B${id}`,
      name: 'unnamed block',
      named: false,
    });
  }
  return out;
}

/** Bars for one job, built from the uploaded files. */
export function barsFor(jobId, { blocks, combos, actions, items, jobs }) {
  if (!blocks) return { available: false, reason: 'no HOTBAR.DAT - upload one' };

  const bars = [];
  for (let bar = 1; bar <= VALID_HOTBARS; bar += 1) {
    const slots = [];
    const records = barSlots(blocks, jobId, bar).slice(0, BINDABLE_SLOTS);
    records.forEach((entry, index) => {
      const number = index + 1;
      const cell = { slot: number, bind: bindName(bar, number), action: entry.value || null };
      if (cell.action) {
        const item = itemFor(cell.action, items);
        if (item) {
          cell.name = item.name;
          cell.icon = item.icon;
          cell.item = item.base;
        } else {
          const name = actions?.[String(cell.action)];
          if (name) {
            cell.name = name;
            cell.icon = `${ICON_BASE}/icon/${cell.action}`;
          } else {
            cell.name = `#${cell.action}`;
          }
        }
      }
      const combo = combos.get(cell.bind);
      if (combo) cell.key = combo;
      slots.push(cell);
    });
    if (slots.some((s) => s.action || s.key)) {
      bars.push({
        bar,
        slots,
        binds: slots.filter((s) => s.key).length,
      });
    }
  }

  const job = (jobs ?? []).find((j) => Number(j.id) === jobId) ?? {};
  return {
    available: true,
    job: {
      id: jobId,
      abbreviation: job.abbreviation ?? `B${jobId}`,
      name: job.name ?? '',
    },
    bars,
  };
}

/** Ability for one bind, used to label a training card. */
export function lookup(jobId, bind, { blocks, actions, items }) {
  const where = parseBindName(bind);
  if (!where || !blocks) return null;
  const action = actionAt(blocks, jobId, where[0], where[1]);
  if (!action) return null;
  const item = itemFor(action, items);
  if (item) {
    return { action, item: item.base, name: item.name, icon: item.icon };
  }
  return {
    action,
    name: actions?.[String(action)] ?? `#${action}`,
    icon: `${ICON_BASE}/icon/${action}`,
  };
}

/** bind name -> combo string, for the binds the trainer deals with. */
export function combosFor(binds) {
  const combos = new Map();
  for (const b of binds) {
    if (b.code === null || b.code === undefined) continue;
    combos.set(b.name, describe(b.mods, b.keyId, b.code));
  }
  return combos;
}

export { BINDABLE_SLOTS };
