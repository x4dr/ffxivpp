import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import { buildKeybind } from './helpers.js';
import {
  KeybindError,
  parse,
  parseTrainable,
} from '../../static/trainer/js/keybind_dat.js';

const parseOne = (name, codes) => {
  const [bind] = parse(buildKeybind([[name, codes]]));
  return bind;
};

test('parses name, codes and modifier bits', () => {
  const bind = parseOne('HOTBAR_1_1', '31.00,00.00,');
  assert.equal(bind.name, 'HOTBAR_1_1');
  assert.equal(bind.keyId, 0x31);
  assert.deepEqual(bind.mods, []);
});

test('modifier bits', () => {
  const cases = [
    ['31.01,00.00,', ['SHIFT']],
    ['31.02,00.00,', ['CTRL']],
    ['31.04,00.00,', ['ALT']],
    ['31.07,00.00,', ['ALT', 'CTRL', 'SHIFT']],
  ];
  for (const [codes, mods] of cases) {
    assert.deepEqual(parseOne('HOTBAR_1_1', codes).mods, mods);
  }
});

test('modifier held in the second slot', () => {
  // Ctrl is written as its own key id in the second slot rather than as bits.
  const bind = parseOne('HOTBAR_1_1', '31.00,11.00,');
  assert.equal(bind.keyId, 0x31);
  assert.deepEqual(bind.mods, ['CTRL']);
  assert.equal(bind.trainable, true);
});

test('bare modifier in the first slot is kept but not trained', () => {
  const bind = parseOne('PERFORMANCE_MODE_OCTAVE_HIGHER', '10.00,B3.00,');
  assert.deepEqual(bind.mods, ['SHIFT']);
  assert.equal(bind.keyId, 0);
  assert.equal(bind.unmappedMod, 0xb3);
  assert.equal(bind.trainable, false);
});

test('a second slot with an unnamed key is not trained', () => {
  const bind = parseOne('HOTBAR_1_1', '31.00,32.00,');
  assert.equal(bind.keyId, 0x31);
  assert.equal(bind.unmappedMod, 0x32);
  assert.equal(bind.trainable, false);
});

test('an unmappable held key is shown but not trained', () => {
  const bind = parseOne('PERFORMANCE_MODE_D4', '57.00,A7.00,');
  assert.equal(bind.keyId, 0x57);
  assert.equal(bind.unmappedMod, 0xa7);
  assert.equal(bind.trainable, false);
});

test('unbound entries are dropped', () => {
  assert.deepEqual(parse(buildKeybind([['MENU', '00.00,00.00,']])), []);
});

test('unknown key id is not trainable', () => {
  const bind = parseOne('MOVE_LEFT', '89.00,00.00,');
  assert.equal(bind.keyId, 0x89);
  assert.equal(bind.code, null);
  assert.equal(bind.trainable, false);
});

test('hotbar 6 resolves to the numpad', () => {
  const records = Array.from({ length: 9 }, (_, i) => [
    `HOTBAR_6_${i + 1}`,
    `${(0x60 + i + 1).toString(16).toUpperCase().padStart(2, '0')}.00,00.00,`,
  ]);
  const binds = parse(buildKeybind(records));
  assert.deepEqual(
    binds.map((b) => b.code),
    ['Numpad1', 'Numpad2', 'Numpad3', 'Numpad4', 'Numpad5', 'Numpad6', 'Numpad7', 'Numpad8', 'Numpad9'],
  );
  assert.ok(binds.every((b) => b.trainable));
});

test('print screen is not a comma', () => {
  const bind = parseOne('KEY_SCREENSHOT', '2C.00,00.00,');
  assert.equal(bind.code, 'PrintScreen');
  assert.equal(bind.label, 'Key screenshot');
});

test('padding after the last record does not raise', () => {
  assert.equal(parse(buildKeybind([['HOTBAR_1_1', '31.00,00.00,']])).length, 1);
});

test('rejects a file that is not a KEYBIND.DAT', () => {
  assert.throws(() => parse(new Uint8Array(64)), (err) => {
    assert.ok(err instanceof KeybindError);
    assert.match(err.message, /not a KEYBIND\.DAT/);
    return true;
  });
});

test('rejects a truncated file', () => {
  assert.throws(
    () => parse(Uint8Array.from([3, 0])),
    (err) => err instanceof KeybindError && /too short/.test(err.message),
  );
});

test('rejects a file cut short of the size its header claims', () => {
  const raw = buildKeybind([['HOTBAR_1_1', '31.00,00.00,']], { truncate: true });
  assert.throws(
    () => parse(raw),
    (err) => err instanceof KeybindError && /truncated/.test(err.message),
  );
});

test('labels read like prose', () => {
  const cases = [
    ['HOTBAR_1_1', 'Bar 1 · slot 1'],
    ['HOTBAR_1_0', 'Bar 1 · slot 10'],
    ['HOTBAR_1_A', 'Bar 1 · slot 11'],
    ['HOTBAR_1_B', 'Bar 1 · slot 12'],
    ['MACRO_14', 'Macro 14'],
  ];
  for (const [name, label] of cases) assert.equal(parseOne(name, '31.00,00.00,').label, label);
});

test('parseTrainable keeps only hotbar binds', () => {
  const raw = buildKeybind([
    ['HOTBAR_1_1', '31.00,00.00,'],
    ['MACRO_1', '31.00,00.00,'],
    ['PERFORMANCE_1', '31.00,00.00,'],
    ['SWARD', '5A.00,00.00,'],
  ]);
  assert.equal(parse(raw).length, 4);
  assert.deepEqual(parseTrainable(raw).map((b) => b.name), ['HOTBAR_1_1']);
});

const REAL = path.join(
  os.homedir(),
  '.xlcore/ffxivConfig/FFXIV_CHR0040002E9398C490/KEYBIND.DAT',
);

test('parses this machine’s real KEYBIND.DAT', { skip: !fs.existsSync(REAL) }, () => {
  const binds = parse(fs.readFileSync(REAL));
  assert.ok(binds.length > 100, `only ${binds.length} binds`);
  const byName = new Map(binds.map((b) => [b.name, b]));
  assert.equal(byName.get('MOVE_STRIFE_L').code, 'KeyA');
  assert.equal(byName.get('MOVE_STRIFE_R').code, 'KeyD');
  assert.equal(byName.get('MENU').code, 'NumpadMultiply');
  assert.equal(byName.get('KEY_SCREENSHOT').code, 'PrintScreen');
  // Numpad binds are the ones that used to come out as letters A-I.
  const numpad = [...byName.values()].filter((b) => b.group === 'HOTBAR' && /Numpad/.test(b.code ?? ''));
  assert.ok(numpad.length >= 9, `only ${numpad.length} numpad hotbar binds`);
});
