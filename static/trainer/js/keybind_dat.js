// Reader for FFXIV's binary KEYBIND.DAT, ported from app/keybind_dat.py.
//
// Container layout, per carriejv/libxivdat:
//
//   header    17 bytes: u32 file_type, u32 max_size, u32 content_size, ...
//   content   max_size bytes, null padded past content_size
//   footer    15 null bytes
//   size      file_size == max_size + 32
//
// Content bytes are XORed with a per-file-type mask (0x73 for KEYBIND). Inside,
// the content is a run of records:
//
//   'T' <u16 len> <name + NUL> 'C' <u16 len> <codes + NUL>
//
// and codes is a comma-separated list of two <keyid>.<modifierbits> pairs,
// both hex, both optional -- so "31.00,00.00," is the key '1' with no
// modifiers and "31.04,00.00," is Alt+1. Modifier bits are 1=Shift, 2=Ctrl,
// 4=Alt.

import { codeFor, MOD_NAMES } from './keys.js';

export const HEADER_SIZE = 17; // 0x11
export const FOOTER_SIZE = 15;
export const MAX_SIZE_OFFSET = HEADER_SIZE + FOOTER_SIZE; // file_size == max_size + this
export const MASK = 0x73;
export const TYPE_ID = 0x00650003; // little-endian u32 at offset 0

// Modifier ids that appear in the second code slot as a standalone held key.
const STANDALONE_MODS = new Map([
  [0x10, 'SHIFT'],
  [0x11, 'CTRL'],
  [0x12, 'ALT'],
]);

export class KeybindError extends Error {
  constructor(message) {
    super(message);
    this.name = 'KeybindError';
  }
}

/** Parse a KEYBIND.DAT and keep only the binds worth training. */
export function parseTrainable(raw) {
  return parse(raw).filter((b) => b.group === 'HOTBAR');
}

/** Parse a KEYBIND.DAT. Returns every bind, not just hotbar ones. */
export function parse(raw) {
  const bytes = toUint8(raw);
  if (bytes.length < HEADER_SIZE + 4) {
    throw new KeybindError('file is too short to be a KEYBIND.DAT');
  }
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);

  const typeId = view.getUint32(0, true);
  if (typeId !== TYPE_ID) {
    throw new KeybindError(
      `not a KEYBIND.DAT: header id is 0x${hex32(typeId)}, expected 0x${hex32(TYPE_ID)}. ` +
        'This looks like a different game config file -- HOTBAR.DAT, COMMON.DAT and ' +
        'the rest share the container shape but have their own type id.',
    );
  }

  const maxSize = view.getUint32(4, true);
  const contentSize = view.getUint32(8, true);
  if (bytes.length !== maxSize + MAX_SIZE_OFFSET) {
    throw new KeybindError(
      `truncated KEYBIND.DAT: ${bytes.length} bytes on disk, header implies ` +
        `${maxSize + MAX_SIZE_OFFSET}`,
    );
  }
  if (contentSize > bytes.length - HEADER_SIZE) {
    throw new KeybindError('truncated KEYBIND.DAT: content runs past the file');
  }

  const body = new Uint8Array(contentSize);
  for (let i = 0; i < contentSize; i += 1) {
    body[i] = bytes[HEADER_SIZE + i] ^ MASK;
  }

  const bindings = [];
  let off = 0;
  while (off + 5 < body.length && body[off] === 0x54 /* 'T' */) {
    let name;
    let codes;
    try {
      [name, codes, off] = readRecord(body, off);
    } catch {
      break; // hit the null padding
    }
    const binding = toBinding(name, codes);
    if (binding) bindings.push(binding);
  }
  return bindings;
}

function readRecord(body, off) {
  const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
  const nameLen = view.getUint16(off + 1, true);
  const nameStart = off + 3;
  const nameEnd = nameStart + nameLen - 1;
  if (nameLen === 0 || nameEnd > body.length) throw new RangeError('short name');
  const name = ascii(body, nameStart, nameEnd);

  const cursor = off + 3 + nameLen;
  if (body[cursor] !== 0x43 /* 'C' */) throw new RangeError('expected codes field');
  const codesLen = view.getUint16(cursor + 1, true);
  const codesEnd = cursor + 3 + codesLen - 1;
  if (codesLen === 0 || codesEnd > body.length) throw new RangeError('short codes');
  const codes = ascii(body, cursor + 3, codesEnd);

  return [name, codes, cursor + 3 + codesLen];
}

function toBinding(name, codes) {
  const mods = new Set();
  let keyId = 0;
  let unmappedMod = 0;

  const groups = codes.split(',').slice(0, 2);
  for (let slot = 0; slot < groups.length; slot += 1) {
    const group = groups[slot];
    if (!group) continue;

    const dot = group.indexOf('.');
    const keyPart = dot >= 0 ? group.slice(0, dot) : group;
    const modPart = dot >= 0 ? group.slice(dot + 1) : '0';
    const rawKey = parseInt(keyPart || '0', 16);

    if (rawKey === 0) continue;

    if (STANDALONE_MODS.has(rawKey)) {
      if (slot === 0) {
        // A bare modifier in the first slot is how FFXIV records e.g.
        // Shift+Space; the real key is whatever the bits say.
        mods.add(STANDALONE_MODS.get(rawKey));
        const bits = parseInt(modPart || '0', 16);
        for (const [bit, mod] of Object.entries(MOD_NAMES)) {
          if (bits & Number(bit)) mods.add(mod);
        }
        continue;
      }
      mods.add(STANDALONE_MODS.get(rawKey));
      continue;
    }

    if (slot === 1) {
      // A second non-modifier key held alongside the main one. We have no
      // name for it, so the bind cannot be checked.
      unmappedMod = rawKey;
      continue;
    }

    keyId = rawKey;
    const bits = parseInt(modPart || '0', 16);
    for (const [bit, mod] of Object.entries(MOD_NAMES)) {
      if (bits & Number(bit)) mods.add(mod);
    }
  }

  if (keyId === 0 && mods.size === 0 && unmappedMod === 0) {
    // Genuinely unbound: FFXIV writes the empty pair for every free bind.
    return null;
  }

  const code = codeFor(keyId);
  return {
    name,
    keyId,
    mods: [...mods].sort(),
    label: labelForBind(name),
    group: name.split('_')[0],
    unmappedMod,
    trainable: code !== null && unmappedMod === 0,
    code,
  };
}

// Raw FFXIV names read badly as prose, so fix up the ones that show up most.
const WORD_FIXUPS = {
  pc: 'player',
  pid: 'party id',
  lh: 'left hand',
  rh: 'right hand',
  ll: 'left',
  lr: 'right',
  up: 'up',
  ex: 'extended',
  id: 'id',
  pad: 'pad',
  tp: 'teleport',
  exp: 'experience',
  cam: 'camera',
  atk: 'attack',
  cmd: 'command',
  ttot: 'top of target',
  tt: 'target',
  tref: 'target reference',
  cw: 'content',
  'ao z': 'aoz',
};

const SLOT_CHARS = '1234567890AB'; // cross hotbar labels run 1..9 then 0, A, B

function labelForBind(name) {
  const parts = name.split('_');

  // HOTBAR_<set>_<slot> and MACRO_<n> are the binds players actually drill.
  if (parts.length === 3 && parts[0] === 'HOTBAR') {
    const slot = parts[2];
    const index = SLOT_CHARS.indexOf(slot);
    const slotNo = index >= 0 ? String(index + 1) : slot;
    return `Bar ${parts[1]} · slot ${slotNo}`;
  }
  if (parts.length === 2 && parts[0] === 'MACRO') {
    return `Macro ${parts[1]}`;
  }

  const words = [];
  parts.forEach((part, i) => {
    const low = part.toLowerCase();
    if (Object.hasOwn(WORD_FIXUPS, low) && !(i === 0 && part === part.toUpperCase())) {
      words.push(i > 0 && part === part.toUpperCase() ? WORD_FIXUPS[low].toUpperCase() : WORD_FIXUPS[low]);
    } else {
      words.push(
        i > 0 ? part.toLowerCase() : part.charAt(0).toUpperCase() + part.slice(1).toLowerCase(),
      );
    }
  });
  return words.join(' ');
}

function ascii(body, start, end) {
  let out = '';
  for (let i = start; i < end; i += 1) out += String.fromCharCode(body[i]);
  return out;
}

function toUint8(raw) {
  if (raw instanceof Uint8Array) return raw;
  if (raw instanceof ArrayBuffer) return new Uint8Array(raw);
  throw new TypeError('expected bytes');
}

function hex32(value) {
  return value.toString(16).toUpperCase().padStart(8, '0');
}
