// HOTBAR.DAT reader, ported from app/hotbar_dat.py.
//
// Layout, solved against the real file with the Dalamud plugin in
// tools/trainer/HotbarDump as ground truth:
//
//   17-byte header, then content XORed with 0x31, then a 15-byte null footer.
//   file_size == max_size + 32
//
//   Records start at offset 132 and are 8 bytes:
//
//     byte 0     page index, measured one position behind the record
//     byte 1     slot index, likewise one behind
//     byte 2     kind -- 1 means "action id in bytes 3..7" (UNCONFIRMED)
//     bytes 3-6  value, little-endian u32 (an action id when kind == 1)
//     byte 7     block index, which is the ClassJob row id
//
// Consecutive records sharing byte 7 form a block. Block 0 is the character's
// own job-independent layout and has 271 records; every other block has 288,
// i.e. 18 bars of 16 slots.
//
// Bind names are HOTBAR_<bar>_<slot> with 1-based bar and a 1-based slot from
// the 12-character alphabet 1234567890AB, so bar 1 slot 3 is position 2 of
// bar 1.

export const TYPE_ID = 0x00040002;
export const MASK = 0x31;
export const HEADER_SIZE = 17;
export const FOOTER_SIZE = 15;

export const RECORD_START = 132;
export const RECORD_SIZE = 8;

// Block 0 holds the character's shared layout rather than a job.
export const GLOBAL_BLOCK = 0;

// ClassJob row ids run 1..45. Blocks above that also appear and are populated
// per-job bars, but what separates them from 1..45 is UNCONFIRMED, so they are
// exposed separately rather than folded into jobIds().
export const MAX_JOB_BLOCK = 45;

// Bar 1 of a job block is its class action bar. Slot indices are 1-based in
// the game's bind names and 0-based in the file.
export const BAR_SLOTS = 16;
export const BINDABLE_SLOTS = 12;

// Crafting actions live above the Action sheet, so their names will not
// resolve. Do not treat a large id as "not an action".
export const FIRST_UNNAMED_ACTION_ID = 100000;

export const SLOT_ALPHABET = '1234567890AB';

/** Unmask the content section of a container. */
export function decode(raw) {
  const bytes = toUint8(raw);
  if (bytes.length < HEADER_SIZE) throw new RangeError('file is too short to decode');
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
  const contentSize = view.getUint32(8, true);
  if (contentSize > bytes.length - HEADER_SIZE) {
    throw new RangeError('truncated container: content runs past the file');
  }
  const body = new Uint8Array(contentSize);
  for (let i = 0; i < contentSize; i += 1) body[i] = bytes[HEADER_SIZE + i] ^ MASK;
  return body;
}

/** Return Map<blockIndex, Slot[]> for a whole HOTBAR.DAT. */
export function parse(raw) {
  const body = decode(raw);
  const view = new DataView(body.buffer, body.byteOffset, body.byteLength);
  const blocks = new Map();
  let current = [];
  let currentIndex = null;
  let position = 0;

  for (let offset = RECORD_START; offset + RECORD_SIZE <= body.length; offset += RECORD_SIZE) {
    const kind = body[offset + 2];
    const value = view.getUint32(offset + 3, true);
    const blockIndex = body[offset + 7];

    if (currentIndex !== null && blockIndex !== currentIndex) {
      blocks.set(currentIndex, current);
      current = [];
      position = 0;
    }
    currentIndex = blockIndex;
    current.push({ position, kind, value });
    position += 1;
  }

  if (currentIndex !== null) blocks.set(currentIndex, current);
  return blocks;
}

/** The id of whatever the slot holds, or null if it is empty. */
export function actionOf(slot) {
  return slot.value || null;
}

/** False for ids the Action sheet cannot name, e.g. crafting actions. */
export function namedByActionSheet(slot) {
  return slot.value > 0 && slot.value < FIRST_UNNAMED_ACTION_ID;
}

/** Record index for a 1-based bar and a 1-based bind slot. */
export function slotForBind(bar, slot) {
  if (bar < 1) throw new RangeError(`bar is 1-based, got ${bar}`);
  if (!(slot >= 1 && slot <= BINDABLE_SLOTS)) {
    throw new RangeError(`slot must be 1..${BINDABLE_SLOTS}, got ${slot}`);
  }
  return (bar - 1) * BAR_SLOTS + (slot - 1);
}

/** HOTBAR_1_3 for bar 1 slot 3. */
export function bindName(bar, slot) {
  if (!(slot >= 1 && slot <= SLOT_ALPHABET.length)) {
    throw new RangeError(`slot must be 1..${SLOT_ALPHABET.length}, got ${slot}`);
  }
  return `HOTBAR_${bar}_${SLOT_ALPHABET[slot - 1]}`;
}

/** HOTBAR_1_3 -> [1, 3]. Null if it is not a hotbar bind. */
export function parseBindName(name) {
  const parts = name.toUpperCase().split('_');
  if (parts.length !== 3 || parts[0] !== 'HOTBAR') return null;
  const bar = Number(parts[1]);
  if (!Number.isInteger(bar)) return null;
  const slot = SLOT_ALPHABET.indexOf(parts[2]);
  if (bar < 1 || slot < 0) return null;
  return [bar, slot + 1];
}

/** Every slot of one block. jobId 0 is the shared layout. */
export function block(blocks, jobId) {
  return blocks.get(jobId) ?? [];
}

/** One slot, by 1-based bar and 1-based bind slot. */
export function slotAt(blocks, jobId, bar, slot) {
  const index = slotForBind(bar, slot);
  const slots = block(blocks, jobId);
  return index < slots.length ? slots[index] : null;
}

/** The action id at one slot, or null. */
export function actionAt(blocks, jobId, bar, slot) {
  const entry = slotAt(blocks, jobId, bar, slot);
  return entry ? actionOf(entry) : null;
}

/** The 16 records of one bar, index 0 == bind slot 1. */
export function barSlots(blocks, jobId, bar) {
  const start = (bar - 1) * BAR_SLOTS;
  return block(blocks, jobId).slice(start, start + BAR_SLOTS);
}

/** Blocks that are class jobs, excluding the shared layout and extras. */
export function jobIds(blocks) {
  return [...blocks.keys()]
    .filter((b) => b > GLOBAL_BLOCK && b <= MAX_JOB_BLOCK)
    .sort((a, b) => a - b);
}

/** Populated blocks above the ClassJob range. */
export function extraBlocks(blocks) {
  return [...blocks.keys()].filter((b) => b > MAX_JOB_BLOCK).sort((a, b) => a - b);
}

function toUint8(raw) {
  if (raw instanceof Uint8Array) return raw;
  if (raw instanceof ArrayBuffer) return new Uint8Array(raw);
  throw new TypeError('expected bytes');
}
