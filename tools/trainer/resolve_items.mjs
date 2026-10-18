#!/usr/bin/env node
// Resolve item ids on hotbars to names and icon paths.
//
// Items do not share the action id space on a hotbar: they are stored as
// 1,000,000 + item id. XIVAPI v1 does not have current items, so names come
// from XIVAPI v2, which reads the same sheets the game does. The result is
// bundled in static/trainer/data/item_index.json, so the browser resolves
// names without the network.
//
// Run after picking a HOTBAR.DAT that contains new items:
//
//     node tools/trainer/resolve_items.mjs [path/to/HOTBAR.DAT]
//
// With no path it uses the most recently written HOTBAR.DAT under
// ~/.xlcore/ffxivConfig, skipping "(copy N)" folders.

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

import { parse } from '../../static/trainer/js/hotbar_dat.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '../..');
const OUT = path.join(ROOT, 'static/trainer/data/item_index.json');
const ITEM_OFFSET = 1_000_000;
const API = (id) => `https://v2.xivapi.com/api/sheet/Item/${id}?fields=Name,Icon`;
const USER_AGENT = 'ffxivpp-trainer/0.1';

function findHotbar() {
  if (process.argv[2]) return path.resolve(process.argv[2]);
  const base = path.join(os.homedir(), '.xlcore/ffxivConfig');
  if (!fs.existsSync(base)) return null;

  let best = null;
  let bestMtime = 0;
  for (const dir of fs.readdirSync(base)) {
    if (dir.includes('(copy')) continue;
    const candidate = path.join(base, dir, 'HOTBAR.DAT');
    if (!fs.existsSync(candidate)) continue;
    const mtime = fs.statSync(candidate).mtimeMs;
    if (mtime > bestMtime) {
      bestMtime = mtime;
      best = candidate;
    }
  }
  return best;
}

function itemIdsOnHotbars(blocks) {
  const found = new Set();
  for (const slots of blocks.values()) {
    for (const slot of slots) {
      // The 2,000,000+ range that also occurs in the file is not understood,
      // so only the verified item offset is resolved.
      if (slot.value >= ITEM_OFFSET && slot.value < 2 * ITEM_OFFSET) {
        found.add(slot.value - ITEM_OFFSET);
      }
    }
  }
  return found;
}

async function fetchItem(baseId) {
  try {
    const res = await fetch(API(baseId), { headers: { 'User-Agent': USER_AGENT } });
    if (!res.ok) {
      console.log(`  ${baseId}: HTTP ${res.status}`);
      return null;
    }
    const payload = await res.json();
    const fields = payload.fields ?? {};
    const name = fields.Name ?? '';
    const icon = fields.Icon?.path_hr1 ?? fields.Icon?.path;
    if (!name || !icon) {
      console.log(`  ${baseId}: no name or icon in the response`);
      return null;
    }
    return { name, icon };
  } catch (err) {
    console.log(`  ${baseId}: ${err.message}`);
    return null;
  }
}

async function main() {
  const hotbar = findHotbar();
  if (!hotbar) {
    console.log('no HOTBAR.DAT found; pass a path as the first argument');
    return 1;
  }

  const blocks = parse(new Uint8Array(fs.readFileSync(hotbar)));
  const ids = itemIdsOnHotbars(blocks);
  if (!ids.size) {
    console.log(`no item slots (ids >= 1,000,000) in ${hotbar}`);
    return 0;
  }

  let index = {};
  try {
    index = JSON.parse(fs.readFileSync(OUT, 'utf8'));
  } catch {
    index = {};
  }

  let added = 0;
  for (const baseId of [...ids].sort((a, b) => a - b)) {
    if (String(baseId) in index) continue;
    const entry = await fetchItem(baseId);
    if (!entry) continue;
    index[String(baseId)] = entry;
    console.log(`  ${baseId}: ${entry.name}`);
    added += 1;
  }

  fs.mkdirSync(path.dirname(OUT), { recursive: true });
  const sorted = Object.fromEntries(
    Object.keys(index)
      .sort((a, b) => Number(a) - Number(b))
      .map((key) => [key, index[key]]),
  );
  fs.writeFileSync(OUT, `${JSON.stringify(sorted, null, 2)}\n`);
  console.log(`wrote ${OUT}: ${Object.keys(sorted).length} items (${added} new)`);
  return 0;
}

process.exitCode = await main();
