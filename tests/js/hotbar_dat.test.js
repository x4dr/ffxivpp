import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { ACTION_KIND, buildHotbar, readU32 } from './helpers.js';
import {
  BAR_SLOTS,
  FIRST_UNNAMED_ACTION_ID,
  GLOBAL_BLOCK,
  RECORD_START,
  actionAt,
  actionOf,
  barSlots,
  bindName,
  decode,
  extraBlocks,
  jobIds,
  namedByActionSheet,
  parse,
  parseBindName,
  slotAt,
  slotForBind,
} from '../../static/trainer/js/hotbar_dat.js';

test('decodes by xor mask', () => {
  const raw = buildHotbar([[[ACTION_KIND, 4242]]]);
  assert.equal(readU32(decode(raw), RECORD_START + 3), 4242);
});

test('splits blocks on the block byte', () => {
  const raw = buildHotbar([[[ACTION_KIND, 1], [ACTION_KIND, 2]], [[ACTION_KIND, 3]]]);
  const blocks = parse(raw);
  assert.deepEqual([...blocks.keys()], [0, 1]);
  assert.deepEqual(blocks.get(0).map(actionOf), [1, 2]);
  assert.deepEqual(blocks.get(1).map(actionOf), [3]);
});

test('positions restart in each block', () => {
  const raw = buildHotbar([
    Array.from({ length: 20 }, (_, i) => [ACTION_KIND, i]),
    [[ACTION_KIND, 99]],
  ]);
  const blocks = parse(raw);
  assert.deepEqual(blocks.get(0).map((s) => s.position), Array.from({ length: 20 }, (_, i) => i));
  assert.deepEqual(blocks.get(1).map((s) => s.position), [0]);
});

test('action is decided by value, not by kind', () => {
  const raw = buildHotbar([[[0, 77], [12, 88], [10, 99]]]);
  assert.deepEqual(parse(raw).get(0).map(actionOf), [77, 88, 99]);
});

test('empty value is not an action', () => {
  assert.equal(actionOf(parse(buildHotbar([[[ACTION_KIND, 0]]])).get(0)[0]), null);
});

test('crafting ids are actions the sheet cannot name', () => {
  const slots = parse(buildHotbar([[[9, 100001], [9, 4631]]])).get(0);
  assert.deepEqual(slots.map(actionOf), [100001, 4631]);
  assert.equal(namedByActionSheet(slots[0]), false);
  assert.equal(namedByActionSheet(slots[1]), true);
});

test('unnamed threshold sits above the sheet', () => {
  assert.ok(FIRST_UNNAMED_ACTION_ID > 51500);
});

test('bind slot is one based', () => {
  assert.equal(slotForBind(1, 3), 2);
});

test('bind name round trips', () => {
  assert.equal(bindName(1, 3), 'HOTBAR_1_3');
  assert.deepEqual(parseBindName('HOTBAR_1_3'), [1, 3]);
});

test('bind alphabet covers twelve slots', () => {
  const names = Array.from({ length: 12 }, (_, i) => bindName(1, i + 1));
  assert.deepEqual(names.slice(-3), ['HOTBAR_1_0', 'HOTBAR_1_A', 'HOTBAR_1_B']);
  names.forEach((name, i) => assert.deepEqual(parseBindName(name), [1, i + 1]));
});

test('bars are sixteen slots apart', () => {
  assert.equal(slotForBind(2, 1), BAR_SLOTS);
});

test('rejects unbindable slots', () => {
  assert.throws(() => slotForBind(1, 13), RangeError);
  assert.throws(() => slotForBind(1, 0), RangeError);
});

test('non hotbar names are not claimed', () => {
  assert.equal(parseBindName('WEAPON_SWAP_NEXT'), null);
  assert.equal(parseBindName('HOTBAR_1_Z'), null);
});

const REAL = path.join(
  os.homedir(),
  '.xlcore/ffxivConfig/FFXIV_CHR0040002E9398C490/HOTBAR.DAT',
);
const needsReal = { skip: !fs.existsSync(REAL) };
const real = needsReal.skip ? null : parse(fs.readFileSync(REAL));

test('header invariant', needsReal, () => {
  const raw = fs.readFileSync(REAL);
  assert.equal(raw.length, readU32(raw, 4) + 32);
});

test('block sizes', needsReal, () => {
  assert.equal(real.get(GLOBAL_BLOCK).length, 271);
  for (const [jobId, slots] of real) {
    if (jobId !== GLOBAL_BLOCK) assert.equal(slots.length, 288, `block ${jobId}`);
  }
});

test('block index is the class job row id', needsReal, () => {
  const ids = [...Array(14)].map((_, i) => i + 1);
  for (const jobId of [...ids, 19, 28, 33, 40]) assert.ok(real.has(jobId), `block ${jobId}`);
});

test('scholar kit matches the game', needsReal, () => {
  const expected = [17869, 17864, 185, 186, 0, 7568, 166, 188, 16537, 7561, 173, 4];
  assert.deepEqual(barSlots(real, 28, 1).slice(0, 12).map(actionOf), expected.map((v) => v || null));
});

test('adloquium is on bar one slot three', needsReal, () => {
  assert.equal(actionAt(real, 28, 1, 3), 185);
});

test('paladin kit matches the game', needsReal, () => {
  const expected = [9, 15, 3539, 7381, 16457, 24, 16460, 3542, 16461, 7548, 30, 4];
  assert.deepEqual(barSlots(real, 19, 1).slice(0, 12).map(actionOf), expected);
});

test('sage kit matches the game', needsReal, () => {
  const expected = [
    24283, 24284, 24286, 24288, 7571, 7568,
    24290, 24304, 24299, 7561, 24287, 4,
  ];
  assert.deepEqual(barSlots(real, 40, 1).slice(0, 12).map(actionOf), expected);
});

test('job block bar one holds a coherent kit', needsReal, () => {
  let filled = 0;
  for (const jobId of jobIds(real)) {
    const actions = barSlots(real, jobId, 1).slice(0, 11).map(actionOf);
    if (actions.filter((a) => a !== null).length >= 7) filled += 1;
  }
  assert.ok(filled >= 40, `only ${filled} filled blocks`);
});

test('most job blocks end their class bar with mount', needsReal, () => {
  const withMount = jobIds(real).filter((j) => actionAt(real, j, 1, 12) === 4);
  assert.ok(withMount.length >= 35, `${withMount.length} blocks`);
});

test('the shared block is not a job kit', needsReal, () => {
  const shared = barSlots(real, GLOBAL_BLOCK, 1).slice(0, 11).map(actionOf);
  assert.ok(shared.filter((a) => a !== null).length <= 2);
});

test('extra blocks are populated per job bars', needsReal, () => {
  const extra = extraBlocks(real);
  assert.ok(extra.length > 0);
  for (const blockId of extra) {
    const filled = barSlots(real, blockId, 1).slice(0, 12).map(actionOf).filter((a) => a !== null).length;
    assert.ok(filled === 0 || filled >= 8, `block ${blockId} has ${filled}`);
  }
});

test('slot lookup matches direct indexing', needsReal, () => {
  for (const [bar, slot] of [[1, 1], [1, 12], [2, 1], [3, 7]]) {
    assert.equal(slotAt(real, 28, bar, slot)?.value, barSlots(real, 28, bar)[slot - 1].value);
  }
});
