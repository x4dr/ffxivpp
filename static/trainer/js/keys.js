// FFXIV key ids -> browser KeyboardEvent.code, plus human labels.
//
// The ids are the game's own SeVirtualKey values, not ASCII. That enum is
// published in FFXIVClientStructs (FFXIV.Client.System.Input.SeVirtualKey)
// and KeySetting.Key is typed as it, so it is the ground truth for what
// KEYBIND.DAT stores:
//
//   0x30-0x39 and 0x41-0x5A are the digit and letter rows;
//   0x60-0x6F are the numpad, so 0x61 is numpad 1 rather than A;
//   0x70-0x7B are F1..F12, and this enum moves NumLock/ScrollLock to
//   0x80/0x81 with F19..F24 after them;
//   mouse buttons and gamepad inputs share the same value space, but a
//   browser cannot see them from a keydown, so they stay unmapped.

export const SHIFT = 1;
export const CTRL = 2;
export const ALT = 4;
export const MOD_NAMES = { [SHIFT]: 'SHIFT', [CTRL]: 'CTRL', [ALT]: 'ALT' };

// id -> [browser code or null, human label]
const KEYS = new Map([
  [0x08, ['Backspace', 'Backspace']],
  [0x09, ['Tab', 'Tab']],
  [0x0c, ['Numpad5', 'Num5']], // VK_CLEAR: numpad 5 with NumLock off
  [0x0d, ['Enter', 'Enter']],
  [0x13, ['Pause', 'Pause']],
  [0x14, ['CapsLock', 'Caps']],
  [0x1b, ['Escape', 'Esc']],
  [0x20, ['Space', 'Space']],
  [0x21, ['PageUp', 'PgUp']],
  [0x22, ['PageDown', 'PgDn']],
  [0x23, ['End', 'End']],
  [0x24, ['Home', 'Home']],
  [0x25, ['ArrowLeft', 'Left']],
  [0x26, ['ArrowUp', 'Up']],
  [0x27, ['ArrowRight', 'Right']],
  [0x28, ['ArrowDown', 'Down']],
  [0x2a, ['PrintScreen', 'PrtSc']],
  [0x2c, ['PrintScreen', 'PrtSc']],
  [0x2d, ['Insert', 'Ins']],
  [0x2e, ['Delete', 'Del']],
  [0x2f, ['Help', 'Help']],
  [0x5b, ['MetaLeft', 'Win']],
  [0x5c, ['MetaRight', 'Win']],
  [0x5d, ['ContextMenu', 'Menu']],
  [0x6a, ['NumpadMultiply', 'Num*']],
  [0x6b, ['NumpadAdd', 'Num+']],
  [0x6c, ['NumpadComma', 'Num,']],
  [0x6d, ['NumpadSubtract', 'Num-']],
  [0x6e, ['NumpadDecimal', 'Num.']],
  [0x6f, ['NumpadDivide', 'Num/']],
  [0x80, ['NumLock', 'NumLock']],
  [0x81, ['ScrollLock', 'ScrLk']],
]);

for (let i = 0; i < 10; i += 1) {
  KEYS.set(0x30 + i, [`Digit${i}`, String(i)]);
  KEYS.set(0x60 + i, [`Numpad${i}`, `Num${i}`]);
}

for (let i = 0; i < 26; i += 1) {
  KEYS.set(0x41 + i, [`Key${String.fromCharCode(0x41 + i)}`, String.fromCharCode(0x41 + i)]);
}

// F1..F16 are contiguous, then this enum skips F17/F18 and resumes at F19.
for (let i = 1; i <= 16; i += 1) {
  KEYS.set(0x6f + i, [`F${i}`, `F${i}`]);
}
let fKey = 19;
for (let id = 0x82; id <= 0x87; id += 1) {
  KEYS.set(id, [`F${fKey}`, `F${fKey}`]);
  fKey += 1;
}

const LABEL_BY_CODE = new Map();
for (const [code, label] of KEYS.values()) {
  if (code) LABEL_BY_CODE.set(code, label);
}

/** Browser event.code for an FFXIV key id, or null if we do not know it. */
export function codeFor(keyId) {
  const entry = KEYS.get(keyId);
  return entry ? entry[0] : null;
}

/** Best guess at a printable name for an FFXIV key id. */
export function labelFor(keyId) {
  const entry = KEYS.get(keyId);
  if (entry) return entry[1];
  return `key 0x${keyId.toString(16).toUpperCase().padStart(2, '0')}`;
}

/** Render a combo the way a player would say it out loud. */
export function describe(mods, keyId, code) {
  const order = ['CTRL', 'ALT', 'SHIFT'].filter((m) => mods.includes(m));
  const name = code === null || code === undefined ? labelFor(keyId) : codeLabel(code);
  return order.length ? [...order, name].join('+') : name;
}

function codeLabel(code) {
  return LABEL_BY_CODE.get(code) ?? code;
}
