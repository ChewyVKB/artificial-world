// Artificial World — close-up mode.
//
// Shows one 12 km patch of the world in detail: the land, water, plants and
// sky, and the people living there going through the day the simulation just
// decided for them — walking out to gather or hunt, fetching water, making
// things, lighting the evening fire, talking, sleeping.
//
// Everything is drawn here on your PC's graphics card. The server only sends
// the coarse map and each person's day (see aworld/closeup.py).
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { Sky } from "three/addons/objects/Sky.js";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";

const CELL = 4000;

// ── deterministic noise (same world seed → same hills, every time) ────────
function hash2(ix, iy, seed) {
  let h = (ix * 374761393 + iy * 668265263 + seed * 2147483647) | 0;
  h = Math.imul(h ^ (h >>> 13), 1274126177);
  h ^= h >>> 16;
  return (h >>> 0) / 4294967296;
}
const fade = (t) => t * t * (3 - 2 * t);
function vnoise(x, y, seed) {
  const ix = Math.floor(x), iy = Math.floor(y), fx = fade(x - ix), fy = fade(y - iy);
  const a = hash2(ix, iy, seed), b = hash2(ix + 1, iy, seed), c = hash2(ix, iy + 1, seed), d = hash2(ix + 1, iy + 1, seed);
  return (a + (b - a) * fx + (c - a) * fy + (a - b - c + d) * fx * fy) * 2 - 1;
}
function fbm(x, y, seed, oct = 5) {
  let s = 0, a = 1, n = 0;
  for (let i = 0; i < oct; i++) { s += a * vnoise(x, y, seed + i * 17); n += a; a *= 0.5; x *= 2.03; y *= 2.03; }
  return s / n;
}
function mulberry(seed) {            // small seeded random generator
  let a = seed >>> 0;
  return () => { a = (a + 0x6D2B79F5) | 0; let t = Math.imul(a ^ (a >>> 15), 1 | a); t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t; return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
}
const smooth = (e0, e1, x) => { const t = Math.min(1, Math.max(0, (x - e0) / (e1 - e0))); return t * t * (3 - 2 * t); };
const lerp = (a, b, t) => a + (b - a) * t;

// Ground colours by biome (linear-ish RGB).
const GROUND = {
  "Ocean": [0.55, 0.50, 0.38], "Lake": [0.45, 0.42, 0.33], "Ice": [0.92, 0.94, 0.97], "Tundra": [0.47, 0.47, 0.38],
  "Boreal forest": [0.20, 0.27, 0.15], "Temperate forest": [0.22, 0.34, 0.14], "Grassland": [0.42, 0.48, 0.22],
  "Desert": [0.78, 0.64, 0.44], "Savanna": [0.60, 0.55, 0.30], "Tropical forest": [0.14, 0.30, 0.10], "Mountain": [0.45, 0.43, 0.40],
};
const TREE_KIND = { "Boreal forest": "conifer", "Temperate forest": "broadleaf", "Tropical forest": "broadleaf",
  "Savanna": "acacia", "Grassland": "broadleaf", "Tundra": "conifer", "Mountain": "conifer" };

// ── the land: a height function shared by terrain, trees, people ─────────
class Land {
  constructor(sc, seed) {
    this.sc = sc; this.seed = seed;
    const c = sc.cells;
    this.span = sc.span; this.E = c.elevation; this.size = sc.span * CELL;
    // Rivers as wandering lines from cell centre to the next cell downstream.
    this.river = [];
    for (const r of c.rivers) {
      if (!r.to) continue;
      const ax = (r.from[0] + 0.5) * CELL, az = (r.from[1] + 0.5) * CELL;
      const bx = (r.to[0] + 0.5) * CELL, bz = (r.to[1] + 0.5) * CELL;
      const len = Math.hypot(bx - ax, bz - az), nx = -(bz - az) / len, nz = (bx - ax) / len;
      const width = Math.min(120, 14 + Math.sqrt(r.flow) * 0.8);
      const pts = [];
      for (let k = 0; k <= 40; k++) {
        const t = k / 40, wob = Math.sin(t * Math.PI) * fbm(ax * 0.001 + t * 3, az * 0.001, seed + 99, 3) * 550;
        pts.push([lerp(ax, bx, t) + nx * wob, lerp(az, bz, t) + nz * wob]);
      }
      this.river.push({ pts, width });
    }
    // Spatial hash of river pieces, so "how far to the river?" is quick.
    this.bin = 400; this.bins = new Map();
    this.river.forEach((rv, ri) => rv.pts.forEach((p, k) => {
      if (k === 0) return;
      const q = rv.pts[k - 1];
      const minx = Math.floor(Math.min(p[0], q[0]) / this.bin) - 1, maxx = Math.floor(Math.max(p[0], q[0]) / this.bin) + 1;
      const minz = Math.floor(Math.min(p[1], q[1]) / this.bin) - 1, maxz = Math.floor(Math.max(p[1], q[1]) / this.bin) + 1;
      for (let i = minx; i <= maxx; i++) for (let j = minz; j <= maxz; j++) {
        const key = i * 100000 + j;
        if (!this.bins.has(key)) this.bins.set(key, []);
        this.bins.get(key).push([q[0], q[1], p[0], p[1], rv.width]);
      }
    }));
    // Lakes sit at the height of their cell.
    this.lakes = [];
    for (let y = 0; y < this.span; y++) for (let x = 0; x < this.span; x++)
      if (c.lake[y][x]) this.lakes.push({ x, y, level: this.E[y][x] });
  }
  cellAt(x, z) {
    const i = Math.min(this.span - 1, Math.max(0, Math.floor(x / CELL))), j = Math.min(this.span - 1, Math.max(0, Math.floor(z / CELL)));
    return [i, j];
  }
  field(name, x, z) {                     // a coarse map value, smoothly blended between cell centres
    const A = this.sc.cells[name];
    const u = Math.min(this.span - 1.001, Math.max(0, x / CELL - 0.5)), v = Math.min(this.span - 1.001, Math.max(0, z / CELL - 0.5));
    const i = Math.floor(u), j = Math.floor(v), fu = fade(u - i), fv = fade(v - j);
    return lerp(lerp(A[j][i], A[j][i + 1], fu), lerp(A[j + 1][i], A[j + 1][i + 1], fu), fv);
  }
  riverDist(x, z) {
    const list = this.bins.get(Math.floor(x / this.bin) * 100000 + Math.floor(z / this.bin));
    let best = 1e9, w = 0;
    if (list) for (const [ax, az, bx, bz, width] of list) {
      const dx = bx - ax, dz = bz - az, t = Math.max(0, Math.min(1, ((x - ax) * dx + (z - az) * dz) / (dx * dx + dz * dz || 1)));
      const d = Math.hypot(x - ax - dx * t, z - az - dz * t);
      if (d < best) { best = d; w = width; }
    }
    return [best, w];
  }
  height(x, z) {
    const base = this.field("elevation", x, z);
    if (base < 0) return base + fbm(x * 0.002, z * 0.002, this.seed, 3) * 8;
    const relief = 12 + Math.pow(Math.max(base, 0), 0.85) * 0.18;
    let h = base + fbm(x * 0.0006, z * 0.0006, this.seed, 5) * relief + fbm(x * 0.004, z * 0.004, this.seed + 5, 3) * relief * 0.18
      + fbm(x * 0.03, z * 0.03, this.seed + 9, 2) * 1.2;
    if (base > 1400) h += Math.pow(1 - Math.abs(fbm(x * 0.0012, z * 0.0012, this.seed + 3, 4)), 3) * (base - 1400) * 0.35;
    const [d, w] = this.riverDist(x, z);
    if (d < w + 400) {                        // rivers cut a channel and a gentle valley
      const valley = 1 - smooth(w * 0.5, w + 400, d);
      h -= valley * Math.min(25, relief * 0.6) + (1 - smooth(w * 0.35, w * 0.6, d)) * 4;
    }
    const [ci, cj] = this.cellAt(x, z);
    if (this.sc.cells.lake[cj][ci]) h = Math.min(h, this.E[cj][ci] - 2 - 6 * smooth(0, 900, Math.min(x % CELL, CELL - x % CELL, z % CELL, CELL - z % CELL)));
    return Math.max(h, base < 5 ? h : 0.5);
  }
  waterAt(x, z) {                            // is this spot under water? (river, lake or sea)
    const h = this.height(x, z);
    if (h < 0) return true;
    const [d, w] = this.riverDist(x, z);
    if (d < w * 0.5) return true;
    const [ci, cj] = this.cellAt(x, z);
    return this.sc.cells.lake[cj][ci] && h < this.E[cj][ci] - 0.5;
  }
  riverSurface(x, z) { return this.height(x, z) + 2.5; }
  biomeAt(x, z) {                            // with the same soft, wandering borders as the ground colour
    const wx = x + fbm(x * 0.0007, z * 0.0007, this.seed + 21, 3) * 900, wz = z + fbm(x * 0.0007, z * 0.0007, this.seed + 22, 3) * 900;
    const [i, j] = this.cellAt(wx, wz);
    return this.sc.cells.biome[j][i];
  }
  groundColour(x, z) {                       // biome colours blended softly from cell to cell (no square edges)
    const wx = x + fbm(x * 0.0007, z * 0.0007, this.seed + 21, 3) * 900, wz = z + fbm(x * 0.0007, z * 0.0007, this.seed + 22, 3) * 900;
    const u = Math.min(this.span - 1.001, Math.max(0, wx / CELL - 0.5)), v = Math.min(this.span - 1.001, Math.max(0, wz / CELL - 0.5));
    const i = Math.floor(u), j = Math.floor(v), fu = smooth(0.2, 0.8, u - i), fv = smooth(0.2, 0.8, v - j);
    const B = this.sc.cells.biome, out = [0, 0, 0];
    for (const [di, dj, w] of [[0, 0, (1 - fu) * (1 - fv)], [1, 0, fu * (1 - fv)], [0, 1, (1 - fu) * fv], [1, 1, fu * fv]]) {
      const g = GROUND[B[j + dj][i + di]] || GROUND.Grassland;
      out[0] += g[0] * w; out[1] += g[1] * w; out[2] += g[2] * w;
    }
    return out;
  }
}

// ── procedural detail texture for the ground ────────────────────────────
function groundTexture() {
  const n = 256, c = document.createElement("canvas");
  c.width = c.height = n;
  const g = c.getContext("2d"), img = g.createImageData(n, n);
  for (let y = 0; y < n; y++) for (let x = 0; x < n; x++) {
    const v = 0.78 + 0.22 * (fbm(x / 9, y / 9, 3, 4) * 0.6 + hash2(x, y, 11) * 0.4);
    const i = 4 * (y * n + x); img.data[i] = img.data[i + 1] = img.data[i + 2] = Math.min(255, v * 255); img.data[i + 3] = 255;
  }
  g.putImageData(img, 0, 0);
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping; t.colorSpace = THREE.SRGBColorSpace; t.anisotropy = 8;
  return t;
}

// ── people: a body made of jointed parts ─────────────────────────────────
const srgb = (r, g, b) => new THREE.Color().setRGB(r, g, b, THREE.SRGBColorSpace);   // colours as you'd pick them in a paint program
const SKIN_LIGHT = srgb(0.93, 0.78, 0.65), SKIN_DARK = srgb(0.32, 0.20, 0.13);
const HAIR = [srgb(0.07, 0.06, 0.05), srgb(0.26, 0.15, 0.08), srgb(0.48, 0.30, 0.15)];
const HIDE = srgb(0.48, 0.35, 0.22), LOIN = srgb(0.40, 0.30, 0.19);
const GEO = {
  limb: new THREE.CapsuleGeometry(1, 1, 4, 10), head: new THREE.SphereGeometry(1, 18, 14),
  torso: new THREE.CapsuleGeometry(1, 1, 6, 14), eye: new THREE.SphereGeometry(1, 8, 6),
};
function limb(mat, r, len) {
  // A limb hanging down from its joint: the pivot is at the top.
  const pivot = new THREE.Group();
  const m = new THREE.Mesh(GEO.limb, mat);
  m.scale.set(r, len / 2, r); m.position.y = -len / 2 - r * 0.2; m.castShadow = true;
  pivot.add(m);
  return pivot;
}
function makePerson(p) {
  const L = p.look, age = p.age;
  const grow = age >= 18 ? 1 : Math.max(0.3, 0.32 + 0.68 * Math.pow(age / 18, 0.75));
  const height = (L.female ? 1.6 : 1.72) * Math.sqrt(L.size) * grow;
  const head = age < 6 ? 0.135 : 0.115;
  const skin = new THREE.MeshStandardMaterial({ color: SKIN_LIGHT.clone().lerp(SKIN_DARK, 1 - L.skin), roughness: 0.75 });
  const clothes = p.carrying.includes("clothing") && age >= 4;
  const cloth = new THREE.MeshStandardMaterial({ color: clothes ? HIDE : LOIN, roughness: 0.95 });
  const hairMat = new THREE.MeshStandardMaterial({ color: HAIR[Math.min(2, Math.floor(L.hair * 3.5))], roughness: 0.9 });
  const root = new THREE.Group(), body = new THREE.Group();
  root.add(body);
  const s = height / 1.7, wide = (L.female ? 0.9 : 1.05) * (0.85 + 0.3 * L.build) * L.size;
  const hips = new THREE.Group(); hips.position.y = 0.95 * s; body.add(hips);
  const spine = new THREE.Group(); hips.add(spine);
  const torso = new THREE.Mesh(GEO.torso, clothes ? cloth : skin);
  torso.scale.set(0.16 * wide * s, 0.2 * s, 0.11 * wide * s); torso.position.y = 0.3 * s; torso.castShadow = true; spine.add(torso);
  const belt = new THREE.Mesh(GEO.torso, cloth); belt.scale.set(0.155 * wide * s, 0.05 * s, 0.115 * wide * s); belt.position.y = 0.04 * s; spine.add(belt);
  const neck = new THREE.Group(); neck.position.y = 0.6 * s; spine.add(neck);
  const headM = new THREE.Mesh(GEO.head, skin); headM.scale.set(head * 0.85, head, head * 0.95); headM.position.y = head * 0.9; headM.castShadow = true; neck.add(headM);
  const hair = new THREE.Mesh(GEO.head, hairMat);
  hair.scale.set(head * 0.9, head * (L.female ? 1.05 : 0.8), head * (L.female ? 1.1 : 0.98));
  hair.position.set(0, head * (L.female ? 0.95 : 1.12), -head * (L.female ? 0.18 : 0.08)); neck.add(hair);
  const eyeMat = new THREE.MeshStandardMaterial({ color: 0x1a120c, roughness: 0.3 });
  for (const sx of [-1, 1]) {
    const e = new THREE.Mesh(GEO.eye, eyeMat); e.scale.setScalar(head * 0.12);
    e.position.set(sx * head * 0.33, head * 1.0, head * 0.82); neck.add(e);
  }
  const nose = new THREE.Mesh(GEO.eye, skin); nose.scale.set(head * 0.14, head * 0.2, head * 0.2); nose.position.set(0, head * 0.82, head * 0.95); neck.add(nose);
  const shoulderW = (L.female ? 0.17 : 0.2) * wide * s;
  const arms = [], legs = [];
  for (const sx of [-1, 1]) {
    const upper = limb(skin, 0.042 * s * wide, 0.27 * s); upper.position.set(sx * shoulderW, 0.52 * s, 0); spine.add(upper);
    const lower = limb(skin, 0.036 * s * wide, 0.25 * s); lower.position.y = -0.3 * s; upper.add(lower);
    arms.push({ upper, lower });
    const thigh = limb(clothes ? cloth : skin, 0.06 * s * wide, 0.4 * s); thigh.position.set(sx * 0.085 * wide * s, 0, 0); hips.add(thigh);
    const shin = limb(skin, 0.047 * s * wide, 0.4 * s); shin.position.y = -0.44 * s; thigh.add(shin);
    legs.push({ thigh, shin });
  }
  root.userData = { pid: p.id, parts: { body, hips, spine, neck, arms, legs }, s, height };
  root.traverse((o) => { if (o.isMesh) o.userData.pid = p.id; });
  // Things they carry, shown when used.
  const prop = {};
  if (p.carrying.includes("spear")) {
    const spear = new THREE.Mesh(new THREE.CylinderGeometry(0.012, 0.015, 2.1, 6), new THREE.MeshStandardMaterial({ color: 0x6b4a2b }));
    const tip = new THREE.Mesh(new THREE.ConeGeometry(0.03, 0.14, 6), new THREE.MeshStandardMaterial({ color: 0x777066, roughness: 0.6 }));
    tip.position.y = 1.1; spear.add(tip); spear.position.y = -0.25 * s; spear.rotation.x = Math.PI / 2;
    arms[1].lower.add(spear); prop.spear = spear; spear.visible = false;
  }
  if (p.carrying.includes("basket")) {
    const b = new THREE.Mesh(new THREE.CylinderGeometry(0.16, 0.11, 0.22, 10, 1, true), new THREE.MeshStandardMaterial({ color: 0x9c7a44, side: THREE.DoubleSide, roughness: 1 }));
    b.position.set(0, 0.32 * s, -0.17 * s); spine.add(b); prop.basket = b;
  }
  if (p.carrying.includes("pot")) {
    const pot = new THREE.Mesh(new THREE.SphereGeometry(0.1, 10, 8), new THREE.MeshStandardMaterial({ color: 0x8a4a2a, roughness: 0.8 }));
    pot.scale.y = 0.9; pot.position.y = -0.28 * s; arms[0].lower.add(pot); prop.pot = pot; pot.visible = false;
  }
  root.userData.prop = prop;
  return root;
}

// Poses: set joint angles for an activity at a moment (phase = seconds-ish clock).
function pose(root, act, phase, moving) {
  const P = root.userData.parts, s = root.userData.s;
  const [aL, aR] = P.arms, [lL, lR] = P.legs;
  const reset = () => {
    P.body.rotation.set(0, 0, 0); P.body.position.set(0, 0, 0); P.spine.rotation.set(0, 0, 0); P.neck.rotation.set(0, 0, 0);
    P.hips.position.y = 0.95 * s;
    for (const a of P.arms) { a.upper.rotation.set(0, 0, 0); a.lower.rotation.set(0, 0, 0); }
    for (const l of P.legs) { l.thigh.rotation.set(0, 0, 0); l.shin.rotation.set(0, 0, 0); }
  };
  reset();
  const walk = (speed, amp) => {
    const w = phase * speed;
    lL.thigh.rotation.x = Math.sin(w) * amp; lR.thigh.rotation.x = -Math.sin(w) * amp;
    lL.shin.rotation.x = Math.max(0, -Math.sin(w + 1.2)) * amp * 1.3; lR.shin.rotation.x = Math.max(0, Math.sin(w + 1.2)) * amp * 1.3;
    aL.upper.rotation.x = -Math.sin(w) * amp * 0.8; aR.upper.rotation.x = Math.sin(w) * amp * 0.8;
    aL.lower.rotation.x = -0.3; aR.lower.rotation.x = -0.3;
    P.body.position.y = Math.abs(Math.cos(w)) * 0.03 * s;
  };
  const sitDown = () => {
    P.hips.position.y = 0.2 * s;
    for (const l of P.legs) { l.thigh.rotation.x = -1.45; l.shin.rotation.x = 1.6; }
    lL.thigh.rotation.z = 0.25; lR.thigh.rotation.z = -0.25;
  };
  const kneel = () => {
    P.hips.position.y = 0.5 * s;
    lL.thigh.rotation.x = -0.3; lL.shin.rotation.x = 1.9; lR.thigh.rotation.x = -1.4; lR.shin.rotation.x = 1.4;
  };
  const lie = (side) => {
    P.body.rotation.z = side ? Math.PI / 2 : 0; P.body.rotation.x = side ? 0 : -Math.PI / 2;
    P.body.position.y = 0.12 * s; P.hips.position.y = 0.95 * s;
    if (side) { P.body.position.x = 0.8 * s; for (const l of P.legs) { l.thigh.rotation.x = -0.6; l.shin.rotation.x = 0.9; } aR.upper.rotation.x = -0.8; }
  };
  if (root.userData.prop.spear) root.userData.prop.spear.visible = act === "hunt" || (act === "walk" && root.userData.hunter);
  if (root.userData.prop.pot) root.userData.prop.pot.visible = act === "drink";
  switch (act) {
    case "walk": case "travel": walk(6, 0.55); break;
    case "play": if (moving) walk(9, 0.75); else { aL.upper.rotation.z = 2.5 + Math.sin(phase * 4) * 0.4; aR.upper.rotation.z = -2.5; } break;
    case "hunt":
      if (moving) { walk(5, 0.5); P.spine.rotation.x = 0.3; aR.upper.rotation.x = -2.6; }
      else { P.hips.position.y = 0.75 * s; P.spine.rotation.x = 0.45; lL.thigh.rotation.x = -0.6; lL.shin.rotation.x = 0.9; lR.thigh.rotation.x = 0.2; lR.shin.rotation.x = 0.6;
        aR.upper.rotation.x = -2.2 - Math.max(0, Math.sin(phase * 0.7)) * 0.9; }
      break;
    case "gather": {
      const c = (Math.sin(phase * 0.9) + 1) / 2;
      if (moving && c < 0.4) walk(5, 0.4);
      else { P.spine.rotation.x = 1.0 * c + 0.2; P.hips.position.y = (0.95 - 0.25 * c) * s; lL.thigh.rotation.x = -0.5 * c; lR.thigh.rotation.x = -0.5 * c;
        lL.shin.rotation.x = 0.8 * c; lR.shin.rotation.x = 0.8 * c; aR.upper.rotation.x = -1.2 * c - Math.sin(phase * 3) * 0.2; aL.upper.rotation.x = -0.9 * c; }
      break;
    }
    case "drink": kneel(); P.spine.rotation.x = 0.9; aL.upper.rotation.x = -1.3; aR.upper.rotation.x = -1.3; aL.lower.rotation.x = -0.6; break;
    case "make":
      sitDown(); P.spine.rotation.x = 0.35; aL.upper.rotation.x = -0.9; aL.lower.rotation.x = -0.9;
      aR.upper.rotation.x = -1.2 + Math.abs(Math.sin(phase * 7)) * -0.6; aR.lower.rotation.x = -1.1; break;
    case "firestart":
      kneel(); P.spine.rotation.x = 0.7;
      aL.upper.rotation.x = -1.2 + Math.sin(phase * 14) * 0.15; aR.upper.rotation.x = -1.2 - Math.sin(phase * 14) * 0.15;
      aL.lower.rotation.x = -0.9; aR.lower.rotation.x = -0.9; break;
    case "sit": case "talk": case "wake":
      sitDown(); aL.upper.rotation.x = -0.5; aR.upper.rotation.x = -0.4; aL.lower.rotation.x = -0.8; aR.lower.rotation.x = -0.8;
      P.neck.rotation.x = Math.sin(phase * 0.3) * 0.1; break;
    case "rest": sitDown(); P.spine.rotation.x = -0.15; aL.upper.rotation.x = 0.3; aR.upper.rotation.x = 0.3; break;
    case "sleep": lie(true); break;
    case "lie_sick": lie(true); P.neck.rotation.x = 0.3; break;
    case "dead": lie(false); break;
    case "carried": sitDown(); break;
  }
}

// ── animals ──────────────────────────────────────────────────────────────
function makeAnimal(kind) {
  const g = new THREE.Group();
  const col = kind === "grazer" ? 0x7a5a3a : 0x4a4a46;
  const mat = new THREE.MeshStandardMaterial({ color: col, roughness: 0.9 });
  const size = kind === "grazer" ? 1 : 0.7;
  const body = new THREE.Mesh(GEO.torso, mat); body.scale.set(0.32 * size, 0.45 * size, 0.3 * size); body.rotation.x = Math.PI / 2; body.position.y = 1.0 * size; body.castShadow = true; g.add(body);
  const neck = new THREE.Group(); neck.position.set(0, 1.15 * size, 0.55 * size); g.add(neck);
  const head = new THREE.Mesh(GEO.head, mat); head.scale.set(0.13 * size, 0.13 * size, 0.24 * size); head.position.set(0, 0.25 * size, 0.18 * size); neck.add(head);
  if (kind === "grazer") for (const sx of [-1, 1]) {
    const horn = new THREE.Mesh(new THREE.ConeGeometry(0.025, 0.3, 5), new THREE.MeshStandardMaterial({ color: 0xd8ccb0 }));
    horn.position.set(sx * 0.07, 0.42, 0.12); horn.rotation.z = -sx * 0.4; neck.add(horn);
  }
  g.userData.legs = [];
  for (const [lx, lz] of [[-1, 1], [1, 1], [-1, -1], [1, -1]]) {
    const leg = limb(mat, 0.05 * size, 0.75 * size); leg.position.set(lx * 0.17 * size, 0.95 * size, lz * 0.42 * size); g.add(leg); g.userData.legs.push(leg);
  }
  g.userData.neck = neck;
  return g;
}

// ── trees, rocks, grass (instanced: thousands for the price of one) ──────
function treeGeometries() {
  const trunk = new THREE.CylinderGeometry(0.18, 0.28, 3, 6).translate(0, 1.5, 0);
  const conifer = mergeGeometries([new THREE.ConeGeometry(1.8, 5, 8).translate(0, 4.2, 0), new THREE.ConeGeometry(1.4, 4, 8).translate(0, 6.2, 0),
    new THREE.ConeGeometry(0.9, 3, 8).translate(0, 8, 0)]);
  const broad = mergeGeometries([new THREE.IcosahedronGeometry(2.4, 1).translate(0, 5.2, 0), new THREE.IcosahedronGeometry(1.8, 1).translate(1.2, 4.4, 0.6),
    new THREE.IcosahedronGeometry(1.7, 1).translate(-1.1, 4.6, -0.5)]);
  const acacia = new THREE.SphereGeometry(3, 10, 6).scale(1, 0.3, 1).translate(0, 3.4, 0);
  const bush = new THREE.IcosahedronGeometry(0.9, 1).scale(1, 0.7, 1).translate(0, 0.5, 0);
  const rock = new THREE.DodecahedronGeometry(1, 0);
  const tuft = mergeGeometries([0, 1, 2].map((k) => new THREE.PlaneGeometry(0.08, 0.55).translate(0, 0.27, 0).rotateY(k * 1.05).rotateZ((k - 1) * 0.25)));
  return { trunk, conifer, broad, acacia, bush, rock, tuft };
}

// ── the close-up view itself ─────────────────────────────────────────────
export class CloseUp {
  constructor(canvas, overlay, api) {
    this.canvas = canvas; this.overlay = overlay; this.api = api;
    this.renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 0.55;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.scene = new THREE.Scene();
    this.camera = new THREE.PerspectiveCamera(50, 1, 0.3, 60000);
    this.controls = new OrbitControls(this.camera, canvas);
    this.controls.maxPolarAngle = 1.52; this.controls.minDistance = 1.5; this.controls.maxDistance = 18000;
    this.controls.enableDamping = true;
    this.sky = new Sky(); this.sky.scale.setScalar(200000); this.scene.add(this.sky);
    {                                               // stars, faded in at night
      const n = 2500, pos = new Float32Array(n * 3), r = mulberry(42);
      for (let i = 0; i < n; i++) {
        const u = r() * 2 - 1, a = r() * Math.PI * 2, h = Math.sqrt(1 - u * u);
        pos.set([h * Math.cos(a) * 50000, Math.abs(u) * 50000, h * Math.sin(a) * 50000], i * 3);
      }
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.BufferAttribute(pos, 3));
      this.stars = new THREE.Points(g, new THREE.PointsMaterial({ color: 0xffffff, size: 1.6, sizeAttenuation: false, transparent: true, fog: false, depthWrite: false }));
      this.scene.add(this.stars);
    }
    this.sun = new THREE.DirectionalLight(0xfff2e0, 3);
    this.sun.castShadow = true; this.sun.shadow.mapSize.set(2048, 2048);
    const sc = this.sun.shadow.camera; sc.left = sc.bottom = -90; sc.right = sc.top = 90; sc.near = 10; sc.far = 3000;
    this.sun.shadow.bias = -0.0004; this.sun.shadow.normalBias = 0.04;
    this.scene.add(this.sun, this.sun.target);
    this.hemi = new THREE.HemisphereLight(0xbcd6ff, 0x3a2e1e, 1.0); this.scene.add(this.hemi);
    this.moon = new THREE.DirectionalLight(0x8fa6d6, 0.0); this.scene.add(this.moon);
    this.pmrem = new THREE.PMREMGenerator(this.renderer);
    this.geo = treeGeometries();
    this._shared = new Set([...Object.values(GEO), ...Object.values(this.geo)]);
    this.groundTex = groundTexture();
    this.world = new THREE.Group(); this.scene.add(this.world);     // the land, water and plants
    this.life = new THREE.Group(); this.scene.add(this.life);       // people, animals, camps
    this.people = new Map(); this.animals = []; this.fires = [];
    this.selected = null; this.follow = true;
    this.hour = 8; this.active = false; this.data = null;
    this.clock = new THREE.Clock();
    this.labels = new Map();
    this._down = null;
    canvas.addEventListener("pointerdown", (e) => (this._down = [e.clientX, e.clientY]));
    canvas.addEventListener("pointerup", (e) => this._click(e));
    new ResizeObserver(() => this.resize()).observe(canvas.parentElement);
    this.onSelect = () => {};
    this._loop = this._loop.bind(this);
  }

  resize() {
    const el = this.canvas.parentElement, w = el.clientWidth, h = el.clientHeight;
    this.renderer.setSize(w, h, false); this.camera.aspect = w / Math.max(h, 1); this.camera.updateProjectionMatrix();
  }

  async open(where) {
    const q = where.person ? `person=${where.person}` : `x=${where.x}&y=${where.y}`;
    const sc = await this.api(`/api/scene?${q}`);
    this.active = true;
    this.build(sc, where.person);
    if (!this._running) { this._running = true; requestAnimationFrame(this._loop); }
  }
  close() { this.active = false; this.overlay.innerHTML = ""; this.labels.clear(); }

  async refresh() {            // a new day has been simulated
    if (!this.active || !this.data) return;
    const f = this.data.focus, sel = this.selected;
    // Stay with the person you're following, even if their family moves away.
    const q = sel && this.people.has(sel) ? `person=${sel}` : `x=${f.x}&y=${f.y}`;
    const sc = await this.api(`/api/scene?${q}`);
    if (!this.active) return;
    this.build(sc, sel, true);
  }

  build(sc, focusPerson, keepCamera = false) {
    const prev = this.data;
    this.data = sc;
    const key = `${sc.origin.x},${sc.origin.y},${sc.focus.x},${sc.focus.y}`;
    // The land only needs re-making when we move somewhere else (or the season has changed).
    const remakeLand = !this.land || key !== this._landKey || Math.abs(sc.tick - this._landTick) >= 30 || !prev;
    dispose(this.life, this._shared); this.people.clear(); this.animals = []; this.fires = [];
    for (const l of this.labels.values()) l.remove();
    this.labels.clear();
    if (remakeLand) {
      dispose(this.world, this._shared);
      this._seed = (sc.origin.x * 73856093) ^ (sc.origin.y * 19349663) ^ 0x5bd1e995;
      this.land = new Land(sc, 1234567 + (sc.origin.x * 31 + sc.origin.y * 977));
      this._landKey = key; this._landTick = sc.tick;
      this._terrain(sc);
      this._water(sc);
      this._plants(sc);
    } else {
      this.land.sc = sc;
    }
    if (remakeLand && keepCamera && prev && (prev.origin.x !== sc.origin.x || prev.origin.y !== sc.origin.y)) {
      // The view slid along with the people: shift the camera by the same amount.
      const dx = (prev.origin.x - sc.origin.x) * CELL, dz = (prev.origin.y - sc.origin.y) * CELL;
      this.camera.position.x += dx; this.camera.position.z += dz; this.controls.target.x += dx; this.controls.target.z += dz;
    }
    this._camps(sc);
    this.homeOf = new Map();
    for (const h of sc.households) h.members.forEach((id, k) => this.homeOf.set(id, { camp: h.camp, slot: k, n: Math.max(h.members.length, 3) }));
    for (const p of sc.people) {
      const body = makePerson(p);
      body.userData.data = p;
      body.userData.hunter = p.timeline.some((s) => s.act === "hunt");
      this.life.add(body);
      this.people.set(p.id, body);
    }
    for (const a of sc.animals) {
      const m = makeAnimal(a.kind);
      m.position.set(a.x, this.land.height(a.x, a.y), a.y); m.rotation.y = a.heading;
      m.userData.home = [a.x, a.y]; m.userData.kind = a.kind; m.userData.phase = Math.random() * 10;
      this.life.add(m); this.animals.push(m);
    }
    // Where to look first: the chosen person, else the busiest camp.
    const fp = focusPerson && this.people.get(focusPerson) ? focusPerson : (sc.people[0] && sc.people[0].id);
    if (fp) this.select(fp, !keepCamera);
    else if (!keepCamera) {
      const fx = (sc.focus.x - sc.origin.x + 0.5) * CELL, fz = (sc.focus.y - sc.origin.y + 0.5) * CELL;
      this.controls.target.set(fx, this.land.height(fx, fz), fz);
      this.camera.position.set(fx + 600, this.land.height(fx, fz) + 400, fz + 600);
    }
  }

  _terrain(sc) {
    const land = this.land, size = land.size;
    const make = (cx, cz, extent, seg, far) => {
      const g = new THREE.PlaneGeometry(extent, extent, seg, seg); g.rotateX(-Math.PI / 2);
      const pos = g.attributes.position, n = pos.count, col = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const x = pos.getX(i) + cx, z = pos.getZ(i) + cz;
        pos.setXYZ(i, x, land.height(x, z), z);
      }
      g.computeVertexNormals();
      const nrm = g.attributes.normal, c = new THREE.Color();
      for (let i = 0; i < n; i++) {
        const x = pos.getX(i), z = pos.getZ(i), y = pos.getY(i);
        const base = land.groundColour(x, z);
        const patch = fbm(x * 0.0025, z * 0.0025, 31, 4), fine = fbm(x * 0.03, z * 0.03, 37, 2);
        const veg = Math.min(1, Math.max(0, land.field("plants", x, z) * 1.4 * (0.8 + 0.45 * patch) + 0.08 * fine));
        c.setRGB(lerp(0.52, base[0], veg), lerp(0.44, base[1], veg), lerp(0.30, base[2], veg));
        const slope = 1 - nrm.getY(i);
        if (slope > 0.12) c.lerp(new THREE.Color(0.42, 0.40, 0.37), smooth(0.12, 0.35, slope));
        const [d, w] = land.riverDist(x, z);
        if (d < w * 1.6) c.lerp(new THREE.Color(0.36, 0.32, 0.24), 1 - smooth(w * 0.6, w * 1.6, d));
        if (y < 3 && y > -2) c.lerp(new THREE.Color(0.76, 0.70, 0.52), 1 - smooth(0, 3, y));
        const snow = land.field("snow", x, z), temp = land.field("temperature", x, z) - (y - land.field("elevation", x, z)) * 0.0065;
        const snowCover = Math.max(smooth(1, 15, snow), smooth(-2, -8, temp)) * (1 - smooth(0.35, 0.6, slope));
        if (snowCover > 0) c.lerp(new THREE.Color(0.93, 0.95, 0.98), snowCover);
        const jitter = 0.92 + 0.16 * hash2(Math.floor(x / 7), Math.floor(z / 7), 5);
        c.multiplyScalar(jitter).convertSRGBToLinear();        // picked as sRGB, the renderer works in linear light
        col[3 * i] = c.r; col[3 * i + 1] = c.g; col[3 * i + 2] = c.b;
      }
      g.setAttribute("color", new THREE.BufferAttribute(col, 3));
      const tex = this.groundTex.clone(); tex.needsUpdate = true; tex.repeat.set(extent / (far ? 120 : 14), extent / (far ? 120 : 14));
      const mat = new THREE.MeshStandardMaterial({ vertexColors: true, map: tex, roughness: 0.97, metalness: 0,
        polygonOffset: far, polygonOffsetFactor: far ? 2 : 0, polygonOffsetUnits: far ? 8 : 0 });
      const mesh = new THREE.Mesh(g, mat); mesh.receiveShadow = true; mesh.userData.ground = true;
      this.world.add(mesh);
      return mesh;
    };
    make(size / 2, size / 2, size, 300, true);                          // the whole 20 km patch
    const f = sc.focus, fx = (f.x - sc.origin.x + 0.5) * CELL, fz = (f.y - sc.origin.y + 0.5) * CELL;
    this.near = make(fx, fz, 2600, 320, false);                         // the land right around the camps, in fine detail
    this.ground = [this.near];
  }

  _water(sc) {
    const land = this.land, size = land.size;
    const waterMat = new THREE.MeshStandardMaterial({ color: 0x1d4560, roughness: 0.08, metalness: 0.1, transparent: true, opacity: 0.88 });
    if (sc.cells.ocean.some((r) => r.some((v) => v))) {
      const sea = new THREE.Mesh(new THREE.PlaneGeometry(size * 3, size * 3).rotateX(-Math.PI / 2), waterMat);
      sea.position.set(size / 2, 0, size / 2); this.world.add(sea);
    }
    for (const lk of land.lakes) {
      const m = new THREE.Mesh(new THREE.PlaneGeometry(CELL * 1.2, CELL * 1.2).rotateX(-Math.PI / 2), waterMat);
      m.position.set((lk.x + 0.5) * CELL, lk.level - 0.6, (lk.y + 0.5) * CELL); this.world.add(m);
    }
    const riverMat = new THREE.MeshStandardMaterial({ color: 0x2a5872, roughness: 0.12, transparent: true, opacity: 0.85 });
    for (const rv of land.river) {
      const verts = [], idx = [];
      const pts = [];
      for (let k = 0; k < rv.pts.length - 1; k++) for (let s = 0; s < 4; s++) {
        const t = s / 4; pts.push([lerp(rv.pts[k][0], rv.pts[k + 1][0], t), lerp(rv.pts[k][1], rv.pts[k + 1][1], t)]);
      }
      pts.forEach((p, k) => {
        const q = pts[Math.min(k + 1, pts.length - 1)], o = pts[Math.max(k - 1, 0)];
        const dx = q[0] - o[0], dz = q[1] - o[1], l = Math.hypot(dx, dz) || 1, nx = -dz / l * rv.width * 0.55, nz = dx / l * rv.width * 0.55;
        const y = Math.max(land.height(p[0], p[1]) + 2.2, 0.3);
        verts.push(p[0] + nx, y, p[1] + nz, p[0] - nx, y, p[1] - nz);
        if (k) { const a = 2 * (k - 1); idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
      });
      const g = new THREE.BufferGeometry(); g.setAttribute("position", new THREE.Float32BufferAttribute(verts, 3)); g.setIndex(idx); g.computeVertexNormals();
      const m = new THREE.Mesh(g, riverMat); m.renderOrder = 1; this.world.add(m);
    }
  }

  _plants(sc) {
    const land = this.land, rnd = mulberry(this._seed);
    const f = sc.focus, fx = (f.x - sc.origin.x + 0.5) * CELL, fz = (f.y - sc.origin.y + 0.5) * CELL;
    const camps = (sc.households || []).map((h) => h.camp);
    const kinds = { conifer: [], broadleaf: [], acacia: [], bush: [], rock: [], tuft: [] };
    const place = (count, radius, scaleBoost) => {
      for (let k = 0; k < count; k++) {
        const r = Math.sqrt(rnd()) * radius, a = rnd() * Math.PI * 2, x = fx + Math.cos(a) * r, z = fz + Math.sin(a) * r;
        if (x < 0 || z < 0 || x > land.size || z > land.size || land.waterAt(x, z)) continue;
        if (camps.some((c) => Math.hypot(c[0] - x, c[1] - z) < 18)) continue;
        const biome = land.biomeAt(x, z);
        const wood = land.field("wood", x, z), veg = land.field("plants", x, z), stone = land.field("stone", x, z);
        const y = land.height(x, z), slope = Math.abs(land.height(x + 4, z) - y) + Math.abs(land.height(x, z + 4) - y);
        const clump = fbm(x * 0.004, z * 0.004, 77, 3);           // trees grow in groves
        if (slope > 3.5 || rnd() < 0.15 * slope) { if (rnd() < 0.4) kinds.rock.push([x, y, z, 0.6 + rnd() * 2.2 * scaleBoost, rnd()]); continue; }
        if (rnd() < wood * (0.55 + clump) && TREE_KIND[biome]) kinds[TREE_KIND[biome]].push([x, y, z, (0.7 + rnd() * 0.7) * scaleBoost, rnd()]);
        else if (rnd() < veg * 0.5) kinds.bush.push([x, y, z, 0.6 + rnd() * 0.8, rnd()]);
        else if (rnd() < stone * 0.3) kinds.rock.push([x, y, z, 0.3 + rnd() * 1.2, rnd()]);
      }
    };
    place(9000, 1300, 1);
    place(5000, 7000, 1.3);
    // Grass tufts close to the camps.
    for (let k = 0; k < 7000; k++) {
      const c = camps.length ? camps[k % camps.length] : [fx, fz];
      const r = Math.sqrt(rnd()) * 160, a = rnd() * Math.PI * 2, x = c[0] + Math.cos(a) * r, z = c[1] + Math.sin(a) * r;
      if (land.waterAt(x, z) || land.field("plants", x, z) < 0.15 || Math.hypot(c[0] - x, c[1] - z) < 6) continue;
      kinds.tuft.push([x, land.height(x, z), z, 0.4 + rnd() * 0.6, rnd()]);
    }
    const mats = {
      trunk: new THREE.MeshStandardMaterial({ color: 0x4a3524, roughness: 1 }),
      conifer: new THREE.MeshStandardMaterial({ color: 0x1f3b24, roughness: 0.95 }),
      broadleaf: new THREE.MeshStandardMaterial({ color: 0x2f5a22, roughness: 0.9 }),
      acacia: new THREE.MeshStandardMaterial({ color: 0x5d6b2a, roughness: 0.9 }),
      bush: new THREE.MeshStandardMaterial({ color: 0x3f5a26, roughness: 0.95 }),
      rock: new THREE.MeshStandardMaterial({ color: 0x77736c, roughness: 0.95, flatShading: true }),
      tuft: new THREE.MeshStandardMaterial({ color: 0x8a9348, roughness: 1, side: THREE.DoubleSide }),
    };
    const m4 = new THREE.Matrix4(), q = new THREE.Quaternion(), e = new THREE.Euler(), v = new THREE.Vector3(), sc3 = new THREE.Vector3();
    const inst = (geo, mat, list, shadow, trunkToo) => {
      if (!list.length) return;
      const mesh = new THREE.InstancedMesh(geo, mat, list.length), trunks = trunkToo ? new THREE.InstancedMesh(this.geo.trunk, mats.trunk, list.length) : null;
      list.forEach(([x, y, z, s, r], i) => {
        e.set(geo === this.geo.rock ? r * 3 : 0, r * 6.28, geo === this.geo.rock ? r * 2 : 0); q.setFromEuler(e);
        m4.compose(v.set(x, y - (geo === this.geo.rock ? s * 0.3 : 0.1), z), q, sc3.set(s, s * (0.85 + r * 0.3), s));
        mesh.setMatrixAt(i, m4); if (trunks) trunks.setMatrixAt(i, m4);
      });
      mesh.castShadow = shadow; mesh.receiveShadow = true; this.world.add(mesh);
      if (trunks) { trunks.castShadow = shadow; this.world.add(trunks); }
    };
    inst(this.geo.conifer, mats.conifer, kinds.conifer, true, true);
    inst(this.geo.broad, mats.broadleaf, kinds.broadleaf, true, true);
    inst(this.geo.acacia, mats.acacia, kinds.acacia, true, true);
    inst(this.geo.bush, mats.bush, kinds.bush, true, false);
    inst(this.geo.rock, mats.rock, kinds.rock, true, false);
    inst(this.geo.tuft, mats.tuft, kinds.tuft, false, false);
  }

  _camps(sc) {
    const land = this.land;
    const stoneMat = new THREE.MeshStandardMaterial({ color: 0x5f5a54, roughness: 1, flatShading: true });
    const ashMat = new THREE.MeshStandardMaterial({ color: 0x1d1a17, roughness: 1 });
    const hideMat = new THREE.MeshStandardMaterial({ color: 0x8a6a45, roughness: 0.95, side: THREE.DoubleSide });
    for (const h of sc.households) {
      const [x, z] = h.camp, y = land.height(x, z);
      const hearth = new THREE.Group(); hearth.position.set(x, y, z);
      for (let k = 0; k < 8; k++) {
        const s = new THREE.Mesh(this.geo.rock, stoneMat); const a = k / 8 * Math.PI * 2;
        s.scale.set(0.13, 0.09, 0.11); s.position.set(Math.cos(a) * 0.45, 0.05, Math.sin(a) * 0.45); s.castShadow = true; hearth.add(s);
      }
      const ash = new THREE.Mesh(new THREE.CircleGeometry(0.4, 12).rotateX(-Math.PI / 2), ashMat); ash.position.y = 0.02; hearth.add(ash);
      if (h.fire) {
        const flames = new THREE.Group();
        for (let k = 0; k < 5; k++) {
          const fl = new THREE.Mesh(new THREE.ConeGeometry(0.12 + Math.random() * 0.06, 0.5 + Math.random() * 0.3, 6),
            new THREE.MeshBasicMaterial({ color: k % 2 ? 0xffb347 : 0xff6a1a, transparent: true, opacity: 0.85 }));
          fl.position.set((Math.random() - 0.5) * 0.25, 0.25, (Math.random() - 0.5) * 0.25); flames.add(fl);
        }
        const logs = new THREE.Mesh(new THREE.CylinderGeometry(0.04, 0.05, 0.7, 5).rotateZ(Math.PI / 2), new THREE.MeshStandardMaterial({ color: 0x3a2716 }));
        logs.position.y = 0.06; hearth.add(logs);
        const logs2 = logs.clone(); logs2.rotation.y = 1.3; hearth.add(logs2);
        const light = new THREE.PointLight(0xff8a3a, 0, 40, 1.5); light.position.y = 0.7; hearth.add(light);
        const sparks = new THREE.Points(new THREE.BufferGeometry().setAttribute("position", new THREE.Float32BufferAttribute(new Float32Array(60 * 3), 3)),
          new THREE.PointsMaterial({ color: 0xffc070, size: 0.05, transparent: true }));
        hearth.add(flames, sparks);
        this.fires.push({ h, flames, light, sparks, start: h.fire_at || 18, stop: 24 });
      }
      if (h.shelter) {                     // a hide shelter: a lean-to of poles and skins
        const tent = new THREE.Mesh(new THREE.ConeGeometry(1.8, 2.4, 7, 1, true), hideMat);
        tent.position.set(2.8, 1.2, 1.5); tent.castShadow = true; tent.receiveShadow = true; hearth.add(tent);
      }
      this.life.add(hearth);
    }
  }

  // Where a person is and what they're doing at an hour of the day.
  _state(p, hour) {
    const tl = p.timeline;
    let seg = tl[tl.length - 1];
    for (const s of tl) if (hour >= s.t0 && hour < s.t1) { seg = s; break; }
    const u = seg.t1 > seg.t0 ? Math.min(1, Math.max(0, (hour - seg.t0) / (seg.t1 - seg.t0))) : 0;
    let x, z, moving = false;
    if (seg.act === "gather" || seg.act === "hunt" || seg.act === "play") {
      // Wander slowly between spots while working.
      const w = (Math.sin(u * Math.PI * 6) + 1) / 2, wob = Math.sin(u * 23) * (seg.act === "play" ? 4 : 10);
      x = lerp(seg.from[0], seg.to[0], w) + wob; z = lerp(seg.from[1], seg.to[1], w) + Math.cos(u * 17) * (seg.act === "play" ? 4 : 10);
      moving = Math.abs(Math.cos(u * Math.PI * 6)) > 0.35;
    } else if (seg.act === "drink" && (seg.from[0] !== seg.to[0] || seg.from[1] !== seg.to[1])) {
      // Walk to the water, then kneel and drink.
      const k = Math.min(1, u / 0.7);
      x = lerp(seg.from[0], seg.to[0], k); z = lerp(seg.from[1], seg.to[1], k);
      if (u < 0.7) return { seg: { ...seg, act: "walk" }, x, z, moving: true, u };
    } else {
      x = lerp(seg.from[0], seg.to[0], u); z = lerp(seg.from[1], seg.to[1], u);
      moving = (seg.act === "walk" || seg.act === "travel") && (seg.from[0] !== seg.to[0] || seg.from[1] !== seg.to[1]);
    }
    // At camp everyone has their own spot around the hearth, not on top of it.
    const home = this.homeOf.get(p.id);
    if (home && !moving && Math.hypot(x - home.camp[0], z - home.camp[1]) < 3) {
      const r = { sleep: 2.6, lie_sick: 2.4, dead: 3.2, firestart: 0.75, make: 2.2 }[seg.act] || 1.7;
      const a = home.slot / home.n * Math.PI * 2 + (seg.act === "sleep" ? 0.3 : 0);
      x = home.camp[0] + Math.cos(a) * r; z = home.camp[1] + Math.sin(a) * r;
    }
    return { seg, x, z, moving, u };
  }

  setHour(h) { this.hour = Math.max(0, Math.min(23.999, h)); }

  _loop() {
    if (!this.active) { this._running = false; return; }
    requestAnimationFrame(this._loop);
    const rawDt = this.clock.getDelta(), dt = Math.min(0.1, rawDt), t = this.clock.elapsedTime;
    this.clock.lastDt = Math.min(1, rawDt);
    if (!this.data) return;
    this._sky(this.hour);
    const land = this.land, hour = this.hour;
    const hh = new Map((this.data.households || []).map((h) => [h.head, h]));
    // People.
    for (const [pid, body] of this.people) {
      const p = body.userData.data;
      let st = this._state(p, hour);
      if (st.seg.act === "carried") {           // babies ride with their mother
        const mom = this.people.get(st.seg.item);
        if (mom) {
          const mp = mom.position, upright = ["walk", "travel", "gather", "hunt", "drink", "play"].includes(mom.userData.act);
          if (upright) {                         // on her hip
            const a = mom.rotation.y;
            body.position.set(mp.x + Math.cos(a) * 0.17, mp.y + mom.userData.height * 0.5, mp.z - Math.sin(a) * 0.17);
            body.rotation.y = a; pose(body, "carried", t, false);
          } else {                               // beside her on the ground, asleep when she sleeps
            const a = mom.rotation.y + Math.PI / 2;
            body.position.set(mp.x + Math.sin(a) * 0.45, mp.y, mp.z + Math.cos(a) * 0.45);
            body.rotation.y = mom.rotation.y; pose(body, mom.userData.act === "sleep" ? "sleep" : "sit", t, false);
          }
          body.userData.act = "carried";
          continue;
        }
      }
      const prev = body.userData.last || [st.x, st.z];
      const dx = st.x - prev[0], dz = st.z - prev[1];
      if (Math.hypot(dx, dz) > 0.02) body.userData.heading = Math.atan2(dx, dz);
      else if (["sit", "rest", "firestart", "make", "wake", "talk"].includes(st.seg.act)) {
        const h = [...hh.values()].find((x) => x.members.includes(pid));
        if (h) body.userData.heading = Math.atan2(h.camp[0] - st.x, h.camp[1] - st.z);
      }
      body.userData.last = [st.x, st.z];
      body.position.set(st.x, land.height(st.x, st.z), st.z);
      body.rotation.y = lerpAngle(body.rotation.y, body.userData.heading || 0, Math.min(1, dt * 6));
      pose(body, st.seg.act, t + pid % 7, st.moving);
      body.userData.act = st.seg.act;
    }
    // Animals graze and drift.
    for (const a of this.animals) {
      a.userData.phase += dt;
      const ph = a.userData.phase, home = a.userData.home;
      const x = home[0] + Math.sin(ph * 0.05 + home[1]) * 25, z = home[1] + Math.cos(ph * 0.04 + home[0]) * 25;
      a.position.set(x, land.height(x, z), z);
      a.userData.neck.rotation.x = 0.6 + Math.sin(ph * 0.6) * 0.5;
    }
    // Fires: lit by someone in the evening, burning into the night.
    for (const f of this.fires) {
      const lit = hour >= f.start + 0.25 && hour < f.stop, catching = hour >= f.start && hour < f.start + 0.25;
      // Burns bright through the evening, then dies down to embers that glow until dawn.
      const k = lit ? 1 - 0.65 * smooth(f.stop - 2.5, f.stop, hour) : catching ? (hour - f.start) / 0.25 : hour < 5.5 ? 0.3 : 0;
      f.flames.visible = k > 0.05;
      f.flames.children.forEach((fl, i) => { fl.scale.set(k, k * (0.8 + 0.35 * Math.sin(t * 9 + i * 1.7)), k); });
      f.light.intensity = k * (18 + 4 * Math.sin(t * 13) + 3 * Math.sin(t * 7.3));
      const pos = f.sparks.geometry.attributes.position;
      for (let i = 0; i < pos.count; i++) {
        const life = (t * 0.7 + i / pos.count) % 1;
        pos.setXYZ(i, Math.sin(i * 12.9 + t) * 0.15 * life, 0.3 + life * 2.2 * (catching ? 0.3 : 1), Math.cos(i * 7.1 + t) * 0.15 * life);
      }
      pos.needsUpdate = true; f.sparks.visible = k > 0.05 || catching; f.sparks.material.opacity = catching ? 1 : 0.6;
    }
    // Camera follows the chosen person.
    if (this.selected && this.follow) {
      const b = this.people.get(this.selected);
      if (b) {
        const target = new THREE.Vector3(b.position.x, b.position.y + 1.0, b.position.z);
        const gap = target.distanceTo(this.controls.target);
        const k = gap > 40 ? 1 : 1 - Math.exp(-this.clock.lastDt * 4);    // glide after them; jump if they're far off
        const delta = target.clone().sub(this.controls.target).multiplyScalar(k);
        this.controls.target.add(delta); this.camera.position.add(delta);
      }
    }
    this.controls.update();
    // Shadows follow the camera's view.
    const tg = this.controls.target;
    this.sun.target.position.copy(tg);
    this.sun.position.copy(tg).add(this._sunDir.clone().multiplyScalar(800));
    this.renderer.render(this.scene, this.camera);
    this._bubbles(hour);
  }

  _sky(hour) {
    const lat = (this.data.latitude ?? 30) * Math.PI / 180, day = this.data.day_of_year || 0, dpy = this.data.days_per_year || 360;
    const decl = 23.4 * Math.PI / 180 * Math.sin(2 * Math.PI * day / dpy);    // seasons tilt the sun (day 0 = spring)
    const H = (hour - 12) / 12 * Math.PI;
    const east = -Math.cos(decl) * Math.sin(H);
    const north = Math.cos(lat) * Math.sin(decl) - Math.sin(lat) * Math.cos(decl) * Math.cos(H);
    const up = Math.sin(lat) * Math.sin(decl) + Math.cos(lat) * Math.cos(decl) * Math.cos(H);
    this._sunDir = new THREE.Vector3(east, up, -north).normalize();         // the view's z axis points south
    const elev = Math.asin(Math.max(-1, Math.min(1, up)));
    const u = this.sky.material.uniforms;
    u.turbidity.value = 6; u.rayleigh.value = 1.6; u.mieCoefficient.value = 0.005; u.mieDirectionalG.value = 0.8;
    u.sunPosition.value.copy(this._sunDir);
    const daylight = smooth(-0.12, 0.25, Math.sin(elev));
    this.sun.intensity = 3.2 * daylight; this.sun.color.setRGB(1, lerp(0.55, 0.95, daylight), lerp(0.35, 0.88, daylight));
    this.hemi.intensity = 0.35 + 0.7 * daylight;
    this.hemi.color.setRGB(lerp(0.35, 0.74, daylight), lerp(0.45, 0.84, daylight), lerp(0.75, 1.0, daylight));
    if (this.stars) this.stars.material.opacity = 1 - smooth(-0.1, 0.05, Math.sin(elev));
    this.moon.intensity = 1.2 * (1 - daylight); this.moon.position.set(-0.3, 1, 0.4);
    this.renderer.toneMappingExposure = lerp(0.4, 0.55, daylight);
    const fogCol = new THREE.Color().setRGB(lerp(0.02, 0.66, daylight), lerp(0.03, 0.74, daylight), lerp(0.06, 0.84, daylight), THREE.SRGBColorSpace);
    if (!this.scene.fog) this.scene.fog = new THREE.FogExp2(fogCol, 0.00006);
    this.scene.fog.color.copy(fogCol);
    if (!this._env || Math.abs(this._envHour - hour) > 0.75) {          // sky reflections in the water, updated now and then
      const tmp = new THREE.Scene(); tmp.add(this.sky.clone());
      if (this._env) this._env.dispose();
      this._env = this.pmrem.fromScene(tmp, 0.04).texture; this.scene.environment = this._env; this._envHour = hour;
      this.scene.environmentIntensity = 0.35 * daylight + 0.03;
    }
  }

  // Speech and thought bubbles, and name tags, drawn over the 3D view.
  _bubbles(hour) {
    const w = this.canvas.clientWidth, h = this.canvas.clientHeight, v = new THREE.Vector3();
    const camPos = this.camera.position;
    const hold = this.speechHold || 0.15;
    const seen = new Set();
    for (const [pid, body] of this.people) {
      const p = body.userData.data;
      const dist = camPos.distanceTo(body.position);
      const sel = pid === this.selected;
      if (dist > (sel ? 600 : 90)) continue;
      v.set(body.position.x, body.position.y + body.userData.height + 0.35, body.position.z).project(this.camera);
      if (v.z > 1 || Math.abs(v.x) > 1.1 || Math.abs(v.y) > 1.1) continue;
      const sx = (v.x * 0.5 + 0.5) * w, sy = (-v.y * 0.5 + 0.5) * h;
      const said = p.speech.filter((s) => hour >= s.t && hour < s.t + hold).pop();
      const thought = sel ? p.thoughts.filter((t) => t.t <= hour && hour < t.t + 1.5).pop() : null;
      let html = "";
      if (said) html += `<div class="say">«${esc(said.word)}»<span>${esc(said.gloss)}</span></div>`;
      if (thought && !said) html += `<div class="think">${esc(thought.text)}</div>`;
      if (dist < 45 || sel) html += `<div class="tag${sel ? " sel" : ""}">${esc(p.name || "#" + p.id)}</div>`;
      if (!html) continue;
      let el = this.labels.get(pid);
      if (!el) { el = document.createElement("div"); el.className = "cu-label"; this.overlay.appendChild(el); this.labels.set(pid, el); }
      if (el._html !== html) { el.innerHTML = html; el._html = html; }
      el.style.transform = `translate(${sx}px, ${sy}px) translate(-50%, -100%)`;
      el.style.display = ""; seen.add(pid);
    }
    for (const [pid, el] of this.labels) if (!seen.has(pid)) el.style.display = "none";
  }

  _click(e) {
    if (!this._down || Math.hypot(e.clientX - this._down[0], e.clientY - this._down[1]) > 4) return;
    const r = this.canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
    const ray = new THREE.Raycaster(); ray.setFromCamera(ndc, this.camera);
    const bodies = [...this.people.values()];
    const hit = ray.intersectObjects(bodies, true)[0];
    if (hit && hit.object.userData.pid) this.select(hit.object.userData.pid, false);
  }

  select(pid, moveCamera) {
    this.selected = pid;
    const b = this.people.get(pid);
    if (b && moveCamera) {
      const st = this._state(b.userData.data, this.hour), y = this.land.height(st.x, st.z);
      this.controls.target.set(st.x, y + 1, st.z);
      this.camera.position.set(st.x + 7, y + 4, st.z + 9);
    }
    this.onSelect(b ? b.userData.data : null);
  }

  activityOf(pid) {
    const b = this.people.get(pid);
    return b ? this._state(b.userData.data, this.hour).seg : null;
  }
}

function dispose(group, keep) {     // free the graphics memory of everything in a group (except shared shapes)
  group.traverse((o) => {
    if (o.geometry && !keep.has(o.geometry)) o.geometry.dispose();
    if (o.material) for (const m of [].concat(o.material)) { if (m.map) m.map.dispose(); m.dispose(); }
  });
  group.clear();
}

function lerpAngle(a, b, t) {
  let d = ((b - a + Math.PI) % (2 * Math.PI)) - Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return a + d * t;
}
const esc = (t) => String(t).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

export const DOING = {
  sleep: "sleeping", wake: "waking up", walk: "walking", gather: "gathering food", hunt: "hunting", drink: "drinking at the water",
  make: "making something", firestart: "lighting the fire", sit: "sitting by the hearth", talk: "talking", carried: "being carried",
  play: "playing", rest: "resting", travel: "moving camp", lie_sick: "lying sick", dead: "dead",
};
