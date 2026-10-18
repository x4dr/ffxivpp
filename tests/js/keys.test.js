import test from 'node:test';
import assert from 'node:assert/strict';

import * as keys from '../../static/trainer/js/keys.js';

const cases = [
  [0x41, 'KeyA', 'A'],
  [0x44, 'KeyD', 'D'],
  [0x31, 'Digit1', '1'],
  [0x60, 'Numpad0', 'Num0'],
  [0x61, 'Numpad1', 'Num1'],
  [0x69, 'Numpad9', 'Num9'],
  [0x6a, 'NumpadMultiply', 'Num*'],
  [0x6b, 'NumpadAdd', 'Num+'],
  [0x6d, 'NumpadSubtract', 'Num-'],
  [0x6e, 'NumpadDecimal', 'Num.'],
  [0x6f, 'NumpadDivide', 'Num/'],
  [0x2c, 'PrintScreen', 'PrtSc'],
  [0x70, 'F1', 'F1'],
  [0x7b, 'F12', 'F12'],
  [0x80, 'NumLock', 'NumLock'],
  [0x81, 'ScrollLock', 'ScrLk'],
  [0x82, 'F19', 'F19'],
  [0x87, 'F24', 'F24'],
];

test('key ids match the game’s enum', () => {
  for (const [id, code, label] of cases) {
    assert.equal(keys.codeFor(id), code, `code for 0x${id.toString(16)}`);
    assert.equal(keys.labelFor(id), label, `label for 0x${id.toString(16)}`);
  }
});

test('inputs a browser cannot see stay unknown', () => {
  for (const id of [0x01, 0x89, 0xa7, 0xba, 0xbd]) {
    assert.equal(keys.codeFor(id), null, `code for 0x${id.toString(16)}`);
  }
});

test('describe says numpad out loud', () => {
  assert.equal(keys.describe(['SHIFT'], 0x61, null), 'SHIFT+Num1');
  assert.equal(keys.describe([], 0x31, 'Digit1'), '1');
  assert.equal(keys.describe(['CTRL', 'ALT'], 0x44, 'KeyD'), 'CTRL+ALT+D');
});
