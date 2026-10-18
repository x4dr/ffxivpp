// Synthetic .DAT builders, ported from the Python tests. They follow the
// documented container shape rather than copying somebody's real file.

export const KEYBIND_MAX_SIZE = 4096;
export const HOTBAR_MAX_SIZE = 4096;
export const ACTION_KIND = 1;

class Bytes {
  constructor() {
    this.parts = [];
  }

  push(...values) {
    this.parts.push(Uint8Array.from(values));
    return this;
  }

  pushBytes(bytes) {
    this.parts.push(bytes);
    return this;
  }

  u16(value) {
    return this.push(value & 0xff, (value >> 8) & 0xff);
  }

  u32(value) {
    return this.push(
      value & 0xff,
      (value >> 8) & 0xff,
      (value >> 16) & 0xff,
      (value >>> 24) & 0xff,
    );
  }

  zeros(count) {
    return this.pushBytes(new Uint8Array(count));
  }

  build() {
    const total = this.parts.reduce((a, p) => a + p.length, 0);
    const out = new Uint8Array(total);
    let at = 0;
    for (const part of this.parts) {
      out.set(part, at);
      at += part.length;
    }
    return out;
  }
}

function ascii(text) {
  return Uint8Array.from([...text].map((ch) => ch.charCodeAt(0)));
}

/** A complete KEYBIND container: header, masked content, padding, footer. */
export function buildKeybind(records, { truncate = false } = {}) {
  const { HEADER_SIZE, FOOTER_SIZE, MASK, TYPE_ID } = keybindConstants();
  const content = new Bytes();
  for (const [name, codes] of records) {
    content.push(0x54, ...[]).u16(name.length + 1).pushBytes(ascii(name)).push(0);
    content.push(0x43).u16(codes.length + 1).pushBytes(ascii(codes)).push(0);
  }
  const body = content.build();

  const header = new Bytes().u32(TYPE_ID).u32(KEYBIND_MAX_SIZE).u32(body.length);
  header.zeros(HEADER_SIZE - 12);

  const masked = body.map((b) => b ^ MASK);
  const padded = new Uint8Array(KEYBIND_MAX_SIZE);
  padded.set(masked);

  const out = new Bytes()
    .pushBytes(header.build())
    .pushBytes(padded)
    .zeros(FOOTER_SIZE)
    .build();
  return truncate ? out.subarray(0, out.length - 10) : out;
}

/** A HOTBAR container whose blocks are lists of [kind, value] pairs. */
export function buildHotbar(blocks, { recordStart = 132 } = {}) {
  const { BAR_SLOTS, HEADER_SIZE, FOOTER_SIZE, MASK, TYPE_ID } = hotbarConstants();
  const content = new Bytes().zeros(recordStart);
  blocks.forEach((records, index) => {
    records.forEach(([kind, value], position) => {
      content.push(
        Math.floor((position - 1) / BAR_SLOTS) & 0xff,
        ((position - 1) % BAR_SLOTS) & 0xff,
        kind,
      );
      content.u32(value);
      content.push(index);
    });
  });
  const body = content.build();

  const header = new Bytes().u32(TYPE_ID).u32(HOTBAR_MAX_SIZE).u32(body.length);
  header.zeros(HEADER_SIZE - 12);

  const masked = body.map((b) => b ^ MASK);
  const padded = new Uint8Array(HOTBAR_MAX_SIZE);
  padded.set(masked);

  return new Bytes()
    .pushBytes(header.build())
    .pushBytes(padded)
    .zeros(FOOTER_SIZE)
    .build();
}

// Read from the modules under test at call time; keeps the builders free of
// import cycles without hardcoding the constants twice.
import * as keybind from '../../static/trainer/js/keybind_dat.js';
import * as hotbar from '../../static/trainer/js/hotbar_dat.js';

function keybindConstants() {
  return keybind;
}

function hotbarConstants() {
  return hotbar;
}

/** Little-endian u32 at offset, for assertions. */
export function readU32(bytes, offset) {
  return new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength).getUint32(offset, true);
}
