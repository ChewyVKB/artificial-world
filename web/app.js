// Artificial World — viewer.
// The server only sends numbers; all drawing happens here, on your PC's GPU.
// three.js (3D library) loads from a CDN. If it can't (offline?), we fall back to the flat map.
let THREE = null, OrbitControls = null, CloseUpMod = null;
try {
  THREE = await import("three");
  ({ OrbitControls } = await import("three/addons/controls/OrbitControls.js"));
  CloseUpMod = await import("./closeup.js");
} catch (err) {
  console.warn("3D unavailable, using the flat map:", err);
}

const $ = (id) => document.getElementById(id);

// Must match aworld/ecology.py BIOMES order.
const BIOMES = ["Ocean", "Lake", "Ice", "Tundra", "Boreal forest", "Temperate forest",
  "Grassland", "Desert", "Savanna", "Tropical forest", "Mountain"];
const BIOME_RGB = [
  [0.10, 0.22, 0.36], [0.16, 0.36, 0.52], [0.92, 0.95, 0.97], [0.55, 0.58, 0.50],
  [0.18, 0.34, 0.24], [0.22, 0.46, 0.22], [0.50, 0.62, 0.30], [0.80, 0.70, 0.48],
  [0.66, 0.62, 0.32], [0.10, 0.40, 0.16], [0.48, 0.45, 0.42],
];
const BARE = [0.55, 0.45, 0.33];          // dry, grazed-out ground
const RIVER = [0.20, 0.45, 0.70];
const SNOW = [0.96, 0.97, 1.0];

// Colour ramps: list of [position 0..1, r, g, b]
const RAMPS = {
  plants: [[0, .45, .36, .26], [.5, .55, .62, .28], [1, .12, .48, .18]],
  grazers: [[0, .16, .17, .16], [.4, .55, .45, .20], [1, 1.0, .85, .35]],
  predators: [[0, .16, .17, .16], [.4, .55, .25, .18], [1, 1.0, .45, .35]],
  temp: [[0, .18, .30, .75], [.47, .90, .93, .95], [.7, .95, .75, .35], [1, .80, .18, .14]],
  rain: [[0, .62, .38, .18], [.5, .90, .90, .86], [1, .18, .42, .80]],
  people: [[0, .14, .15, .15], [.02, .45, .30, .55], [.3, .95, .55, .35], [1, 1.0, .95, .75]],
  mood: [[0, .55, .18, .22], [.35, .78, .45, .28], [.6, .85, .80, .45], [1, .40, .85, .55]],
  knowledge: [[0, .14, .15, .15], [.05, .30, .25, .50], [.5, .45, .60, .90], [1, .85, .95, 1.0]],
  stone: [[0, .16, .17, .16], [1, .85, .85, .80]],
  clay: [[0, .16, .17, .16], [1, .80, .45, .30]],
  wood: [[0, .16, .17, .16], [1, .30, .60, .25]],
};
const PERSON = [1.0, 0.82, 0.45];         // how people show up on the map
// Distinct colours for languages (by language id).
const LANG_RGB = [[.95, .55, .35], [.40, .75, .95], [.70, .90, .40], [.90, .45, .80], [.98, .85, .35], [.45, .90, .80],
  [.85, .35, .40], [.60, .55, .95], [.95, .70, .60], [.55, .80, .55], [.80, .80, .80], [.35, .55, .85]];
const langColor = (id) => LANG_RGB[(id - 1) % LANG_RGB.length];
const LEGENDS = {
  plants: ["Vegetation", "bare", "lush"],
  grazers: ["Grazing herds (density)", "none", "dense"],
  predators: ["Predators (density)", "none", "dense"],
  temp: ["Temperature today", "−40 °C", "+45 °C"],
  rain: ["Rain this year vs. normal", "−50%", "+50%"],
  people: ["People per cell (~16 km²)", "0", "20+"],
  knowledge: ["Techniques known per person (average)", "0", "10"],
  mood: ["How people feel (average)", "wretched", "happy"],
  stone: ["Flint (knappable stone)", "none", "plenty"],
  clay: ["Clay", "none", "plenty"],
  wood: ["Wood", "none", "plenty"],
};

function ramp(name, t, out) {
  const r = RAMPS[name];
  for (let k = 1; k < r.length; k++) {
    if (t <= r[k][0] || k === r.length - 1) {
      const a = r[k - 1], b = r[k];
      const u = Math.min(1, Math.max(0, (t - a[0]) / (b[0] - a[0] || 1)));
      out[0] = a[1] + (b[1] - a[1]) * u; out[1] = a[2] + (b[2] - a[2]) * u; out[2] = a[3] + (b[3] - a[3]) * u;
      return out;
    }
  }
  return out;
}
const mix = (a, b, t, out) => { out[0] = a[0] + (b[0] - a[0]) * t; out[1] = a[1] + (b[1] - a[1]) * t; out[2] = a[2] + (b[2] - a[2]) * t; return out; };

// ── state ─────────────────────────────────────────────────────
const S = {
  worldId: null, W: 0, H: 0, N: 0,
  elev: null, biome: null, water: null, shade: null,
  frame: null, tick: -1, dpy: 360,
  layer: "natural", view: "3d", running: false,
  status: null, lastMajorTick: -1, selected: null,
};

// ── API ───────────────────────────────────────────────────────
async function api(path, body) {
  const opt = body === undefined ? {} : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const r = await fetch(path, opt);
  if (!r.ok) throw new Error(`${path}: ${r.status}`);
  return r.headers.get("Content-Type")?.includes("json") ? r.json() : r;
}

async function loadTerrain() {
  const r = await fetch("/api/terrain");
  S.W = +r.headers.get("X-Width"); S.H = +r.headers.get("X-Height"); S.N = S.W * S.H;
  S.worldId = r.headers.get("X-World");
  const buf = await r.arrayBuffer();
  S.elev = new Int16Array(buf.slice(0, S.N * 2));
  S.biome = new Uint8Array(buf, S.N * 2, S.N);
  S.water = new Uint8Array(buf, S.N * 3, S.N);
  const mats = buf.byteLength >= S.N * 7;            // older servers didn't send materials
  S.mat = {
    stone: mats ? new Uint8Array(buf, S.N * 4, S.N) : new Uint8Array(S.N),
    clay: mats ? new Uint8Array(buf, S.N * 5, S.N) : new Uint8Array(S.N),
    wood: mats ? new Uint8Array(buf, S.N * 6, S.N) : new Uint8Array(S.N),
  };
  // Hill-shading for the flat map: light from the north-west.
  S.shade = new Float32Array(S.N);
  for (let y = 0; y < S.H; y++) for (let x = 0; x < S.W; x++) {
    const i = y * S.W + x;
    const e = Math.max(0, S.elev[i]);
    const ex = Math.max(0, S.elev[y * S.W + Math.max(0, x - 1)]);
    const ey = Math.max(0, S.elev[Math.max(0, y - 1) * S.W + x]);
    S.shade[i] = Math.min(1.25, Math.max(0.65, 1 + ((e - ex) + (e - ey)) / 900));
  }
  S.frame = null; S.tick = -1;
  build3D();
  build2D();
}

async function loadFrame() {
  const r = await fetch("/api/frame");
  const tick = +r.headers.get("X-Tick");
  const buf = await r.arrayBuffer();
  if (buf.byteLength !== S.N * 10) return;          // world switched mid-flight
  S.frame = new Uint8Array(buf);
  S.tick = tick;
  paint();
}
const L = (k) => S.frame.subarray(k * S.N, (k + 1) * S.N);   // 0 plants 1 grazers 2 predators 3 snow 4 temp 5 rain 6 people 7 knowledge 8 language 9 mood

// ── colouring (shared by 3D and 2D) ───────────────────────────
function cellColor(i, out) {
  const b = S.biome[i];
  const ocean = b === 0, lake = b === 1 || S.water[i] === 2;
  if (ocean) {
    const d = Math.min(1, -S.elev[i] / 3500);
    out[0] = 0.12 - 0.07 * d; out[1] = 0.27 - 0.14 * d; out[2] = 0.42 - 0.16 * d;
    return out;
  }
  if (lake) return mix(BIOME_RGB[1], BIOME_RGB[1], 0, out);
  const f = S.frame;
  const layer = S.layer;
  if (layer === "mood" && f) {
    const m = f[9 * S.N + i];
    if (m) ramp("mood", (m - 1) / 254, out);
    else { out[0] = .16; out[1] = .17; out[2] = .16; }
    return out;
  }
  if (layer === "language" && f) {
    const id = f[8 * S.N + i];
    if (id) { const c = langColor(id); out[0] = c[0]; out[1] = c[1]; out[2] = c[2]; }
    else { out[0] = .16; out[1] = .17; out[2] = .16; }
    return out;
  }
  if (layer === "biome") {
    out[0] = BIOME_RGB[b][0]; out[1] = BIOME_RGB[b][1]; out[2] = BIOME_RGB[b][2];
  } else if (layer === "natural" || !f) {
    const p = f ? f[i] / 255 : 0.6;
    mix(BARE, BIOME_RGB[b], Math.min(1, p * 1.6), out);
    if (f) {
      const snow = f[3 * S.N + i] / 255;
      if (snow > 0) mix(out, SNOW, Math.min(1, snow * 2.5), out);
    }
  } else {
    let v;
    if (S.mat[layer]) v = S.mat[layer][i] / 255;
    else {
      const k = { plants: 0, grazers: 1, predators: 2, temp: 4, rain: 5, people: 6, knowledge: 7 }[layer];
      v = layer === "people" ? Math.min(1, Math.sqrt(f[k * S.N + i] / 20))
        : layer === "knowledge" ? (f[6 * S.N + i] ? 0.02 + f[k * S.N + i] / 250 : 0)
        : f[k * S.N + i] / 255;
    }
    ramp(layer, v, out);
  }
  if (S.water[i] === 1 && (layer === "natural" || layer === "biome")) mix(out, RIVER, 0.85, out);
  return out;
}

// ── 3D view ───────────────────────────────────────────────────
const three = { renderer: null, scene: null, camera: null, controls: null, mesh: null, colors: null, marker: null };

function init3D() {
  const canvas = $("view3");
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));
  const scene = new THREE.Scene();
  scene.background = null;
  const camera = new THREE.PerspectiveCamera(45, 1, 0.5, 5000);
  const controls = new OrbitControls(camera, canvas);
  controls.maxPolarAngle = 1.45;
  controls.addEventListener("change", render);
  scene.add(new THREE.HemisphereLight(0xdfe9ff, 0x2a2016, 1.2));
  const sun = new THREE.DirectionalLight(0xfff1dc, 1.8);
  scene.add(sun);
  Object.assign(three, { renderer, scene, camera, controls, sun });
  new ResizeObserver(resize).observe($("viewport"));

  // Click (without dragging) to inspect.
  let down = null;
  canvas.addEventListener("pointerdown", (e) => { down = [e.clientX, e.clientY]; });
  canvas.addEventListener("pointerup", (e) => {
    if (!down || Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 4 || !three.mesh) return;
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, camera);
    const hit = ray.intersectObject(three.mesh)[0];
    if (hit) inspect(Math.round(hit.point.x + (S.W - 1) / 2), Math.round(hit.point.z + (S.H - 1) / 2));
  });
}

const vScale = () => S.W * 0.09;            // how tall mountains look
function heightAt(i) {
  const e = S.elev[i];
  return e > 0 ? (e / 4500) * vScale() : Math.max(e / 4000 * 8, -8);
}

function build3D() {
  if (!THREE) return;
  const { scene, camera, controls } = three;
  if (three.mesh) { scene.remove(three.mesh); three.mesh.geometry.dispose(); }
  if (three.water) { scene.remove(three.water); }
  const geo = new THREE.PlaneGeometry(S.W - 1, S.H - 1, S.W - 1, S.H - 1);
  geo.rotateX(-Math.PI / 2);                 // vertex i == map cell i; north is "away" from you
  const pos = geo.attributes.position;
  for (let i = 0; i < S.N; i++) pos.setY(i, heightAt(i));
  geo.computeVertexNormals();
  three.colors = new Float32Array(S.N * 3);
  geo.setAttribute("color", new THREE.BufferAttribute(three.colors, 3));
  three.mesh = new THREE.Mesh(geo, new THREE.MeshLambertMaterial({ vertexColors: true, flatShading: true }));
  scene.add(three.mesh);

  const water = new THREE.Mesh(
    new THREE.PlaneGeometry(S.W * 3, S.H * 3).rotateX(-Math.PI / 2),
    new THREE.MeshPhongMaterial({ color: 0x1d4d78, transparent: true, opacity: 0.72, shininess: 80 }));
  water.position.y = -0.05;
  three.water = water;
  scene.add(water);

  if (!three.marker) {
    three.marker = new THREE.Mesh(new THREE.ConeGeometry(1.2, 4, 12), new THREE.MeshBasicMaterial({ color: 0xffe08a }));
    three.marker.rotation.x = Math.PI;
    three.marker.visible = false;
    scene.add(three.marker);
  }
  three.sun.position.set(-S.W * 0.8, S.W * 0.9, -S.H * 0.3);
  scene.fog = new THREE.Fog(0x0b0f12, S.W * 1.4, S.W * 3.2);
  camera.position.set(0, S.W * 0.62, S.H * 0.78);
  controls.target.set(0, 0, 0);
  controls.maxDistance = S.W * 2.2;
  controls.minDistance = 8;
  controls.update();
  paint();
}

// People in 3D: one little standing figure per occupied cell, taller where more people live.
function updatePeople3D() {
  if (!three.scene || !S.frame) return;
  const counts = S.frame.subarray(6 * S.N, 7 * S.N);
  let n = 0;
  for (let i = 0; i < S.N; i++) if (counts[i]) n++;
  if (!three.people || three.peopleCap < n) {
    if (three.people) { three.scene.remove(three.people); three.people.dispose(); }
    const cap = Math.max(256, n * 2);
    const geo = new THREE.CylinderGeometry(0.28, 0.38, 1, 6).translate(0, 0.5, 0);
    const mat = new THREE.MeshLambertMaterial({ color: 0xffc46b, emissive: 0x4a2a00 });
    three.people = new THREE.InstancedMesh(geo, mat, cap);
    three.people.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
    three.peopleCap = cap;
    three.scene.add(three.people);
  }
  const m = new THREE.Matrix4(), q = new THREE.Quaternion(), sc = new THREE.Vector3(), p = new THREE.Vector3();
  let k = 0;
  for (let i = 0; i < S.N; i++) {
    const c = counts[i];
    if (!c) continue;
    const x = i % S.W, y = (i / S.W) | 0;
    p.set(x - (S.W - 1) / 2, heightAt(i), y - (S.H - 1) / 2);
    sc.set(1, 0.8 + Math.log2(1 + c) * 0.9, 1);
    three.people.setMatrixAt(k++, m.compose(p, q, sc));
  }
  three.people.count = k;
  three.people.instanceMatrix.needsUpdate = true;
  three.people.visible = !["people", "knowledge", "language", "mood"].includes(S.layer);
}

function resize() {
  const el = $("viewport");
  const w = el.clientWidth, h = el.clientHeight;
  three.renderer.setSize(w, h, false);
  three.camera.aspect = w / Math.max(h, 1);
  three.camera.updateProjectionMatrix();
  render();
}

let renderQueued = false;
function render() {
  if (!THREE || renderQueued || S.view !== "3d") return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; three.renderer.render(three.scene, three.camera); });
}

// ── 2D map ────────────────────────────────────────────────────
const flat = { ctx: null, img: null };
function build2D() {
  const c = $("view2");
  c.width = S.W; c.height = S.H;
  flat.ctx = c.getContext("2d");
  flat.img = flat.ctx.createImageData(S.W, S.H);
}
$("view2").addEventListener("click", (e) => {
  const c = e.currentTarget, rect = c.getBoundingClientRect();
  const scale = Math.min(rect.width / S.W, rect.height / S.H);
  const ox = (rect.width - S.W * scale) / 2, oy = (rect.height - S.H * scale) / 2;
  const x = Math.floor((e.clientX - rect.left - ox) / scale), y = Math.floor((e.clientY - rect.top - oy) / scale);
  if (x >= 0 && y >= 0 && x < S.W && y < S.H) inspect(x, y);
});

// ── painting ──────────────────────────────────────────────────
const tmp = [0, 0, 0];
function paint() {
  if (!S.N) return;
  if (S.view === "3d" && three.colors) {
    const c = three.colors;
    // three.js expects vertex colours in linear space; ours are sRGB, so convert (≈ gamma 2.2).
    for (let i = 0; i < S.N; i++) {
      cellColor(i, tmp);
      c[3 * i] = tmp[0] ** 2.2; c[3 * i + 1] = tmp[1] ** 2.2; c[3 * i + 2] = tmp[2] ** 2.2;
    }
    three.mesh.geometry.attributes.color.needsUpdate = true;
    updatePeople3D();
    render();
  } else if (S.view === "2d" && flat.img) {
    const d = flat.img.data;
    const shadeOn = S.layer === "natural" || S.layer === "biome";
    const ppl = S.frame && !["people", "knowledge", "language", "mood"].includes(S.layer) ? S.frame.subarray(6 * S.N, 7 * S.N) : null;
    for (let i = 0; i < S.N; i++) {
      cellColor(i, tmp);
      if (ppl && ppl[i]) mix(tmp, PERSON, Math.min(1, 0.85 + ppl[i] / 40), tmp);
      const s = shadeOn ? S.shade[i] : 1;
      d[4 * i] = Math.min(255, tmp[0] * s * 255); d[4 * i + 1] = Math.min(255, tmp[1] * s * 255);
      d[4 * i + 2] = Math.min(255, tmp[2] * s * 255); d[4 * i + 3] = 255;
    }
    if (S.selected) {
      const [sx, sy] = S.selected;
      for (let k = -3; k <= 3; k++) for (const [x, y] of [[sx + k, sy], [sx, sy + k]]) {
        if (x < 0 || y < 0 || x >= S.W || y >= S.H || k === 0) continue;
        const j = 4 * (y * S.W + x); d[j] = 255; d[j + 1] = 224; d[j + 2] = 138;
      }
    }
    flat.ctx.putImageData(flat.img, 0, 0);
  }
  drawLegend();
}

function drawLegend() {
  const el = $("legend");
  if (S.layer === "language") {
    const langs = (S.languages || []).filter((l) => !l.died_year);
    el.innerHTML = "<div>Languages spoken (most common in each place)</div>" + (langs.length
      ? langs.map((l) => `<div><span class="sw" style="background:rgb(${langColor(l.id).map((v) => v * 255 | 0)})"></span>${escapeHtml(l.name)}</div>`).join("")
      : "<div class='muted'>none yet</div>");
    return;
  }
  if (S.layer === "natural" || S.layer === "biome") {
    const used = new Set(S.biome);
    el.innerHTML = `<div>${S.layer === "natural" ? "Natural colours · bare ground = brown · snow = white" : "Biomes"}</div><div class="grid">` +
      BIOMES.map((b, k) => used.has(k) ? `<div><span class="sw" style="background:rgb(${BIOME_RGB[k].map(v => v * 255 | 0)})"></span>${b}</div>` : "").join("") + "</div>";
    return;
  }
  const [title, lo, hi] = LEGENDS[S.layer];
  const stops = RAMPS[S.layer].map(([p, r, g, b]) => `rgb(${r * 255 | 0},${g * 255 | 0},${b * 255 | 0}) ${p * 100}%`).join(",");
  el.innerHTML = `<div>${title}</div><div class="ramp" style="background:linear-gradient(90deg,${stops})"></div><div class="ends"><span>${lo}</span><span>${hi}</span></div>`;
}

// ── inspector ─────────────────────────────────────────────────
function placeMarker(x, y) {
  S.selected = [x, y];
  if (three.marker) {
    three.marker.position.set(x - (S.W - 1) / 2, heightAt(y * S.W + x) + 2.5, y - (S.H - 1) / 2);
    three.marker.visible = true;
  }
}
async function inspect(x, y) {
  S.personId = null; S.follow = false;
  placeMarker(x, y);
  paint();
  await refreshInspector();
}
async function showPerson(id) {
  S.personId = id;
  await refreshInspector();
}
// Clicks inside the inspector (people lists, family links, buttons).
$("inspector").addEventListener("click", async (e) => {
  const t = e.target.closest("[data-person],[data-action]");
  if (!t) return;
  if (t.dataset.person) return showPerson(+t.dataset.person);
  if (t.dataset.action === "back") { S.personId = null; S.follow = false; return refreshInspector(); }
  if (t.dataset.action === "follow") { S.follow = !S.follow; return refreshInspector(); }
  if (t.dataset.action === "closeup") return enterCloseUp({ x: S.selected[0], y: S.selected[1] });
  if (t.dataset.action === "closeup-person") return enterCloseUp({ person: S.personId });
});

const kv = (rows) => `<dl class="kv">${rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("")}</dl>`;
const link = (r, label) => r ? `<a href="#" data-person="${r.id}">${label ?? (r.name ? escapeHtml(r.name) : "#" + r.id)}</a>${r.alive ? "" : ' <span class="muted">†</span>'}` : "—";
const bar = (v) => `<span class="meter"><span style="width:${Math.round(v * 100)}%"></span></span>`;

async function refreshInspector() {
  if (S.personId) return renderPerson(await api(`/api/person?id=${S.personId}`));
  if (!S.selected) return;
  const [c, here] = await Promise.all([
    api(`/api/cell?x=${S.selected[0]}&y=${S.selected[1]}`),
    api(`/api/people?x=${S.selected[0]}&y=${S.selected[1]}`),
  ]);
  const rows = [
    ["Place", `${c.x}, ${c.y}`], ["Biome", c.biome],
    ["Elevation", c.elevation_m >= 0 ? `${c.elevation_m} m` : `${-c.elevation_m} m deep`],
    ["Latitude", `${Math.abs(c.latitude)}° ${c.latitude >= 0 ? "N" : "S"}`],
    ["Temperature now", `${c.temperature_c} °C`], ["Yearly average", `${c.yearly_avg_temp_c} °C`],
    ["Yearly rain", `${c.yearly_rain_mm} mm`],
  ];
  if (c.river) rows.push(["Water", "river"]);
  if (c.lake) rows.push(["Water", "lake"]);
  if (c.vegetation_pct !== undefined) rows.push(
    ["Vegetation", `${c.vegetation_pct}% (max ${c.vegetation_capacity_pct}%)`],
    ["Grazing animals", `≈ ${c.grazers}`], ["Predators", `≈ ${c.predators}`],
    ["Snow", `${c.snow_cm} cm`], ["Rain this year", `${c.rain_this_year_vs_normal_pct >= 0 ? "+" : ""}${c.rain_this_year_vs_normal_pct}% vs normal`]);
  let people = "";
  if (here.length) {
    const shown = here.slice(0, 40);
    people = `<h4>${here.length} ${here.length === 1 ? "person" : "people"} here</h4><ul class="plist">${shown.map((p) =>
      `<li><a href="#" data-person="${p.id}">${p.name ? escapeHtml(p.name) : "#" + p.id}</a><span>${p.sex === "female" ? "♀" : "♂"} ${p.age} yrs${p.mood ? ` · ${escapeHtml(p.mood)}` : ""}</span>${bar(p.health)}</li>`).join("")}</ul>` +
      (here.length > shown.length ? `<div class="muted small">…and ${here.length - shown.length} more</div>` : "");
  }
  const watch = CloseUpMod && c.vegetation_pct !== undefined && c.biome !== "Ocean"
    ? `<button class="watch-btn primary" data-action="closeup">👁 Watch this place up close</button>` : "";
  $("inspectBody").innerHTML = kv(rows) + watch + people;
}

function renderPerson(p) {
  if (p.error) { $("inspectBody").innerHTML = `<div class="muted">${escapeHtml(p.error)}</div><button data-action="back">Back</button>`; return; }
  if (S.follow && p.alive && p.location) {
    placeMarker(p.location.x, p.location.y);
    followCamera(p.location.x, p.location.y);
  }
  const rows = [
    ["Sex", p.sex], ["Generation", p.generation],
    ["Born", `year ${p.born_year}`],
  ];
  if (p.alive) {
    rows.push(["Age", `${p.age} years`], ["Health", bar(p.health)], ["Fed", bar(p.energy)], ["Water", bar(p.hydration)]);
    if (p.pregnant) rows.push(["", "expecting a child"]);
    if (p.vocabulary) rows.push(["Speaks", p.speaks ? escapeHtml(p.speaks) : (p.vocabulary.length ? "a few words of their own" : "no words yet")]);
    if (p.accent && p.accent.length) rows.push(["Accent", `<span title="sound rules they speak with">${p.accent.map(escapeHtml).join(", ")}</span>`]);
    rows.push(["Travels with", `${p.household_size} ${p.household_size === 1 ? "person" : "people"}`],
              ["Where", `${p.location.x}, ${p.location.y}`]);
  } else {
    rows.push(["Died", `year ${p.died_year}, aged ${p.age_at_death}`], ["Cause", p.cause_of_death || "—"]);
  }
  rows.push(["Mother", link(p.mother)], ["Father", link(p.father)]);
  if (p.alive) rows.push(["Partner", link(p.partner)]);
  const kids = p.children.length
    ? p.children.map((c) => link(c, `${c.name ? escapeHtml(c.name) : "#" + c.id}${c.sex === "female" ? "♀" : "♂"}`)).join(" ")
    : "none";
  const traits = p.traits ? Object.entries(p.traits).map(([k, v]) =>
    [k, `${bar(k === "size" ? (v - 0.6) / 0.8 : v)} ${v.toFixed(2)}`]) : [];
  $("inspectBody").innerHTML = `
    <div class="person-head">
      <span class="pid">${p.name ? escapeHtml(p.name) : "#" + p.id}</span>${p.name ? `<span class="muted small">#${p.id}</span>` : ""}${p.alive ? "" : '<span class="muted"> · died</span>'}
      <span class="spacer"></span>
      ${p.alive ? `<button data-action="follow" class="${S.follow ? "on" : ""}">${S.follow ? "Following" : "Follow"}</button>` : ""}
      <button data-action="back">Back</button>
    </div>
    ${p.alive && CloseUpMod ? `<button class="watch-btn primary" data-action="closeup-person">👁 Watch ${p.name ? escapeHtml(p.name) : "them"} up close</button>` : ""}
    ${kv(rows)}
    <h4>Children (${p.children.length})</h4><div class="kids">${kids}</div>
    ${p.knows ? `<h4>Knows how to make (${p.knows.length})</h4>${p.knows.length ? kv(p.knows.map((k) => [k.name, bar(k.skill)])) : '<div class="muted small">nothing yet</div>'}` : ""}
    ${p.mind ? renderMind(p.mind) : ""}
    ${p.carrying && p.carrying.length ? `<h4>Carrying</h4><div class="small">${p.carrying.map(escapeHtml).join(" · ")}</div>` : ""}
    ${p.vocabulary && p.vocabulary.length ? `<h4>Their words (${p.vocabulary.length})</h4><div class="vocab">${p.vocabulary.map((v) =>
      `<span title="${escapeHtml(v.meaning)} · ${Math.round(v.sure * 100)}% sure"><b>${escapeHtml(v.word)}</b> ${escapeHtml(v.meaning)}</span>`).join("")}</div>` : ""}
    ${traits.length ? `<h4>Inherited traits</h4>${kv(traits)}` : ""}
    ${p.name ? "" : `<p class="muted small">${p.vocabulary ? "No name — their mother had too few words to name a child." : "People have no names yet — names need a language, and language hasn't been invented."}</p>`}`;
}

function followCamera(x, y) {
  if (!THREE || S.view !== "3d") return;
  const target = new THREE.Vector3(x - (S.W - 1) / 2, heightAt(y * S.W + x), y - (S.H - 1) / 2);
  const delta = target.sub(three.controls.target);
  three.controls.target.add(delta);
  three.camera.position.add(delta);
  three.controls.update();
}

// ── charts ────────────────────────────────────────────────────
function lineChart(canvas, series, dpy, opts = {}) {
  const dpr = window.devicePixelRatio || 1;
  const w = canvas.clientWidth, h = canvas.height / (canvas._dpr || 1);
  canvas._dpr = dpr;
  canvas.width = w * dpr; canvas.height = h * dpr;
  const g = canvas.getContext("2d");
  g.scale(dpr, dpr);
  g.clearRect(0, 0, w, h);
  const all = series.flatMap((s) => s.data);
  if (all.length < 2) { g.fillStyle = "#8a938f"; g.font = "12px IBM Plex Mono"; g.fillText("collecting data…", 8, h / 2); return; }
  const x0 = Math.min(...all.map((p) => p[0])), x1 = Math.max(...all.map((p) => p[0]));
  const ymax = opts.ymax ?? Math.max(1, ...all.map((p) => p[1])) * 1.08;
  const pad = { l: 40, r: 6, t: 6, b: 16 };
  const X = (t) => pad.l + ((t - x0) / Math.max(1, x1 - x0)) * (w - pad.l - pad.r);
  const Y = (v) => h - pad.b - (v / ymax) * (h - pad.t - pad.b);
  g.strokeStyle = "#242a2e"; g.fillStyle = "#8a938f"; g.font = "10px IBM Plex Mono"; g.lineWidth = 1;
  for (const f of [0, 0.5, 1]) {
    const v = ymax * f;
    g.beginPath(); g.moveTo(pad.l, Y(v)); g.lineTo(w - pad.r, Y(v)); g.stroke();
    g.fillText(fmt(v), 2, Y(v) + 3);
  }
  g.fillText(`yr ${Math.floor(x0 / dpy)}`, pad.l, h - 3);
  const end = `yr ${Math.floor(x1 / dpy)}`;
  g.fillText(end, w - pad.r - g.measureText(end).width, h - 3);
  for (const s of series) {
    if (s.data.length < 2) continue;
    g.strokeStyle = s.color; g.lineWidth = 1.6; g.beginPath();
    s.data.forEach(([t, v], k) => (k ? g.lineTo(X(t), Y(v)) : g.moveTo(X(t), Y(v))));
    g.stroke();
  }
  let lx = pad.l + 4, ly = pad.t + 2;
  for (const s of series) {
    const wdt = g.measureText(s.label).width + 24;
    if (lx + wdt > w - pad.r && lx > pad.l + 4) { lx = pad.l + 4; ly += 12; }
    g.fillStyle = s.color; g.fillRect(lx, ly, 8, 8);
    g.fillStyle = "#e4e7e5"; g.fillText(s.label, lx + 11, ly + 7);
    lx += wdt;
  }
}
function fmt(v) {
  if (v >= 1e6) return (v / 1e6).toFixed(1) + "M";
  if (v >= 1e3) return (v / 1e3).toFixed(v >= 1e4 ? 0 : 1) + "k";
  return v >= 10 ? Math.round(v) + "" : v.toFixed(1);
}

const TRAIT_COLORS = { size: "#e4e7e5", insulation: "#6fb3e0", fertility: "#e07a9f", longevity: "#b39ddb", wanderlust: "#e2b65c", sociability: "#7bc96f", curiosity: "#5fd3c4", speech: "#f0a0ff" };
async function refreshCharts() {
  const traitNames = Object.keys(TRAIT_COLORS).map((t) => "trait_" + t).join(",");
  const m = await api(`/api/metrics?names=grazers,predators,vegetation_pct,drought_area_pct,population,births_per_year,deaths_per_year,techniques_known,techniques_per_person,languages,words_per_person,feel_joy,feel_fear,feel_grief,feel_lonely,${traitNames}&points=400`);
  const s = m.series, css = getComputedStyle(document.documentElement);
  const hasPeople = (s.population || []).length > 0;
  $("peopleCharts").hidden = !hasPeople;
  if (hasPeople) {
    lineChart($("chartPeople"), [
      { label: "population", color: "#ffc46b", data: s.population || [] },
      { label: "births/yr", color: "#7bc96f", data: s.births_per_year || [] },
      { label: "deaths/yr", color: "#e07a5f", data: s.deaths_per_year || [] },
    ], m.days_per_year);
    lineChart($("chartTraits"), Object.entries(TRAIT_COLORS).map(([t, color]) => ({
      label: t === "size" ? "size*" : t, color,
      data: (s["trait_" + t] || []).map(([k, v]) => [k, t === "size" ? (v - 0.6) / 0.8 : v]),
    })), m.days_per_year, { ymax: 1 });
  }
  const hasMind = (s.feel_joy || []).length > 0;
  $("mindCard").hidden = !hasMind;
  if (hasMind) lineChart($("chartFeelings"), [
    { label: "joy", color: "#7bc96f", data: s.feel_joy },
    { label: "fear", color: "#e07a5f", data: s.feel_fear || [] },
    { label: "grief", color: "#9ec5ff", data: s.feel_grief || [] },
    { label: "loneliness", color: "#e2b65c", data: s.feel_lonely || [] },
  ], m.days_per_year, { ymax: 1 });
  const hasLanguage = (s.words_per_person || []).length > 0;
  $("languageCard").hidden = !hasLanguage;
  if (hasLanguage) {
    lineChart($("chartLanguage"), [
      { label: "languages", color: "#f0a0ff", data: s.languages || [] },
      { label: "words per person", color: "#ffc46b", data: s.words_per_person || [] },
    ], m.days_per_year);
    refreshLanguages();
  }
  const hasKnowledge = (s.techniques_known || []).length > 0;
  $("knowledgeCard").hidden = !hasKnowledge;
  if (hasKnowledge) {
    lineChart($("chartKnowledge"), [
      { label: "techniques anyone knows", color: "#9ec5ff", data: s.techniques_known || [] },
      { label: "known per person", color: "#5fd3c4", data: s.techniques_per_person || [] },
    ], m.days_per_year, { ymax: 10 });
    refreshKnowledge();
  }
  lineChart($("chartPop"), [
    { label: "grazers", color: css.getPropertyValue("--grazer"), data: s.grazers || [] },
    { label: "predators ×10", color: css.getPropertyValue("--predator"), data: (s.predators || []).map(([t, v]) => [t, v * 10]) },
  ], m.days_per_year);
  lineChart($("chartClimate"), [
    { label: "vegetation", color: css.getPropertyValue("--accent"), data: s.vegetation_pct || [] },
    { label: "drought area", color: "#c9a26b", data: s.drought_area_pct || [] },
  ], m.days_per_year, { ymax: 100 });
}

async function refreshHistory() {
  const ev = await api("/api/events?limit=120");
  $("history").innerHTML = ev.map((e) => `<li class="${/EXTINCT|FAMINE|PEOPLE|NEW_LAND|FIRST_BIRTH|GROUPS|CREATED|POPULATION|DISCOVERY|LOST|WORD|NAME|LANGUAGE/.test(e.type) ? "major" : ""}">${escapeHtml(e.title)}</li>`).join("")
    || `<li class="muted">Nothing notable yet.</li>`;
}
const escapeHtml = (t) => t.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

const FEEL_LABEL = { joy: "Joy", fear: "Fear", grief: "Grief", lonely: "Loneliness" };
function renderMind(m) {
  const mem = m.memories.slice(0, 12).map((x) => `<li><span class="fade" style="opacity:${0.35 + 0.65 * Math.min(1, x.strength)}">${
      x.strength >= 0.5 ? "vivid" : x.strength >= 0.2 ? "clear" : "faint"}</span><b>year ${x.year}</b>${x.person && x.person.id
      ? escapeHtml(x.text).replace(escapeHtml(x.person.name || "#" + x.person.id), link(x.person))
      : escapeHtml(x.text)}</li>`).join("");
  return `<h4>Mind</h4>
    ${kv([["Feels", escapeHtml(m.mood)], ["Wants to", escapeHtml(m.goal)],
          ...Object.entries(m.feelings).map(([k, v]) => [FEEL_LABEL[k] || k, bar(v)])])}
    <h4>Remembers (${m.memories.length})</h4>
    ${mem ? `<ol class="memories">${mem}</ol>` : '<div class="muted small">nothing that stuck</div>'}`;
}

// ── status / controls ─────────────────────────────────────────
const SEASONS_N = ["Spring", "Summer", "Autumn", "Winter"];
function applyStatus(st) {
  S.status = st; S.running = st.running; S.dpy = st.days_per_year;
  $("worldName").textContent = st.world.name;
  $("worldSeed").textContent = `seed ${st.world.seed} · v${st.world.sim_version}`;
  $("clockYear").textContent = `Year ${st.year.toLocaleString()}`;
  const q = Math.floor((st.day_of_year / st.days_per_year) * 4) % 4;
  $("clockDay").textContent = `Day ${st.day_of_year + 1} · ${SEASONS_N[q]} in the north, ${SEASONS_N[(q + 2) % 4]} in the south`;
  const b = $("btnPlay");
  b.textContent = st.running ? "❚❚ Pause" : "▶ Start";
  b.classList.toggle("running", st.running);
  const sel = $("speed");
  if (!sel.options.length) for (const s of st.speeds) sel.add(new Option(s, s));
  if (document.activeElement !== sel) sel.value = st.speed;
  $("sGrazers").textContent = fmt(st.now.grazers);
  $("sPeople").textContent = st.people ? st.people.population.toLocaleString() : "none";
  $("sPeopleSub").textContent = st.people ? `${st.people.births_this_year} born · ${st.people.deaths_this_year} died this year` : "";
  $("sVeg").textContent = `${st.now.vegetation_pct}%`;
  $("sSpeed").textContent = st.running ? `${fmt(st.days_per_sec)} d/s` : "paused";
  $("pauseMajor").checked = st.pause_on_major;
  $("errorBanner").hidden = !st.error;
  $("errorBanner").textContent = st.error ? `${st.error} — check the log with: docker compose logs` : "";
  const sto = st.storage;
  $("storage").textContent = `Disk: ${(sto.world_bytes / 1e6).toFixed(1)} MB of ${(sto.cap_bytes / 1e9).toFixed(0)} GB cap · ${sto.checkpoints} checkpoints`;
  if (cu.on) cuStatus(st);
  if (st.last_major && st.last_major.tick !== S.lastMajorTick) {
    if (S.lastMajorTick !== -1) toast(st.last_major.title);
    S.lastMajorTick = st.last_major.tick;
  }
}
let toastTimer;
function toast(text) {
  const t = $("toast");
  t.textContent = text; t.hidden = false;
  clearTimeout(toastTimer); toastTimer = setTimeout(() => (t.hidden = true), 6000);
}

async function control(body) { applyStatus(await api("/api/control", body)); }
$("btnPlay").onclick = () => control({ action: S.running ? "pause" : "play" });
$("btnDay").onclick = async () => { await control({ action: "step", days: 1 }); await loadFrame(); };
$("btnYear").onclick = async () => { await control({ action: "step", days: S.dpy }); await loadFrame(); };
$("speed").onchange = (e) => control({ action: "speed", speed: e.target.value });
$("pauseMajor").onchange = (e) => control({ action: "pause_on_major", value: e.target.checked });
$("btnSave").onclick = async () => { applyStatus(await api("/api/save", {})); toast("Checkpoint saved."); };
$("btnSeek").onclick = async () => {
  const year = Math.max(0, +$("seekYear").value || 0);
  toast(`Travelling to year ${year}… (re-simulating from the nearest checkpoint)`);
  applyStatus(await api("/api/seek", { tick: year * S.dpy }));
  await Promise.all([loadFrame(), refreshCharts(), refreshHistory()]);
  toast(`Now at year ${S.status.year}.`);
};
$("layer").onchange = (e) => { S.layer = e.target.value; paint(); };
for (const [id, view] of [["view3d", "3d"], ["view2d", "2d"]]) {
  $(id).onclick = () => {
    S.view = view;
    $("view3d").classList.toggle("on", view === "3d"); $("view2d").classList.toggle("on", view === "2d");
    $("view3").hidden = view !== "3d"; $("view2").hidden = view !== "2d";
    document.querySelector(".hint").textContent = view === "3d"
      ? "Drag to orbit · right-drag to pan · scroll to zoom · click land to inspect" : "Click land to inspect";
    paint();
  };
}
window.addEventListener("keydown", (e) => {
  if (e.code === "Space" && !["INPUT", "SELECT"].includes(document.activeElement.tagName)) { e.preventDefault(); $("btnPlay").click(); }
});

async function refreshLanguages() {
  const L = await api("/api/languages");
  if (!L.enabled) return;
  S.languages = L.languages;
  if (S.layer === "language") drawLegend();
  const living = L.languages.filter((l) => !l.died_year).sort((a, b) => b.speakers - a.speakers);
  const dead = L.languages.filter((l) => l.died_year);
  const row = (l) => `<li class="lang ${l.died_year ? "dead" : ""}">
      <details ${S.openLang === l.id ? "open" : ""} data-lang="${l.id}">
        <summary><span class="sw" style="background:rgb(${langColor(l.id).map((v) => v * 255 | 0)})"></span>
          <span class="lname">${escapeHtml(l.name)}</span>
          <span class="lstat">${l.died_year ? `spoken until year ${l.died_year}` : `${l.speakers.toLocaleString()} speakers · ${l.words.length} words${l.dialects && l.dialects.length ? ` · ${l.dialects.length} dialects` : ""}`}</span></summary>
        <div class="lsub">since year ${l.born_year}${l.parent ? ` · descended from ${escapeHtml(l.parent)}` : ""}</div>
        ${l.dialects && l.dialects.length ? `<div class="dialects">${l.dialects.map((d) => `<div class="dialect">
            <span class="dname">${escapeHtml(d.name)}</span> <span class="muted">${d.speakers.toLocaleString()} speakers</span>
            ${d.differences.length ? `<div class="dsub">${d.differences.map((x) =>
              `says <b>${escapeHtml(x.word)}</b> for ${escapeHtml(x.meaning)} <span class="muted">(not ${escapeHtml(x.standard)})</span>`).join(" · ")}</div>` : ""}
          </div>`).join("")}</div>` : ""}
        <div class="vocab">${l.words.map((w) => `<span><b>${escapeHtml(w.word)}</b> ${escapeHtml(w.meaning)}</span>`).join("")}</div>
      </details></li>`;
  $("langList").innerHTML = (living.map(row).join("") || `<li class="muted small">No shared language yet — people have only a few words of their own.</li>`)
    + (dead.length ? `<li class="muted small" style="margin-top:6px">No longer spoken</li>` + dead.slice(-8).reverse().map(row).join("") : "");
}
$("langList").addEventListener("toggle", (e) => {
  const d = e.target.closest("details");
  if (d) S.openLang = d.open ? +d.dataset.lang : (S.openLang === +d.dataset.lang ? null : S.openLang);
}, true);

async function refreshKnowledge() {
  const k = await api("/api/knowledge");
  if (!k.enabled) return;
  const order = { known: 0, lost: 1, undiscovered: 2 };
  const rows = [...k.techniques].sort((a, b) => order[a.status] - order[b.status]);
  $("techList").innerHTML = rows.map((t) => {
    const pct = k.population ? Math.round(100 * t.knowers / k.population) : 0;
    const when = t.status === "known" ? `${pct}% know it` + (t.carrying !== null ? ` · ${t.carrying} carry one` : "")
      : t.status === "lost" ? `lost in year ${t.lost_year}` : "never discovered";
    const first = t.first_year !== null && t.first_year !== undefined ? `first: year ${t.first_year} by <a href="#" data-person="${t.first_by}">#${t.first_by}</a>` : "";
    return `<li class="tech ${t.status}" title="${escapeHtml(t.does)} · needs ${t.needs.join(" + ")}">
      <div class="tname">${escapeHtml(t.name)}</div><div class="tstat">${when}</div>
      <div class="tsub">${first}${t.times_lost ? ` · lost ${t.times_lost}×` : ""}</div></li>`;
  }).join("");
}
$("techList").addEventListener("click", (e) => {
  const a = e.target.closest("[data-person]");
  if (a) { e.preventDefault(); showPerson(+a.dataset.person); }
});

// Worlds dialog
$("btnWorlds").onclick = async () => {
  const { current, worlds } = await api("/api/worlds");
  $("worldList").innerHTML = worlds.map((w) => `<li><div>${escapeHtml(w.name)}<div class="meta">seed ${w.seed} · created ${w.created_utc.slice(0, 10)}</div></div>
    <div class="row-btns">${w.id === current ? `<span class="muted small">open</span>` : `<button type="button" data-open="${w.id}">Open</button>`}
    <button type="button" class="danger" data-delete="${w.id}" data-name="${escapeHtml(w.name)}">Delete</button></div></li>`).join("");
  $("worldList").querySelectorAll("[data-delete]").forEach((b) => (b.onclick = async () => {
    if (!confirm(`Delete "${b.dataset.name}" permanently?\n\nIts whole history and every save will be erased. This can't be undone.`)) return;
    const before = S.worldId;
    await api("/api/worlds/delete", { id: b.dataset.delete });
    toast(`Deleted "${b.dataset.name}".`);
    $("worldsDialog").close();
    applyStatus(await api("/api/status"));
    if (S.status.world.id !== before) { await loadTerrain(); await Promise.all([loadFrame(), refreshCharts(), refreshHistory()]); }
  }));
  $("worldList").querySelectorAll("[data-open]").forEach((b) => (b.onclick = async () => {
    applyStatus(await api("/api/worlds/open", { id: b.dataset.open }));
    $("worldsDialog").close(); await loadTerrain(); await Promise.all([loadFrame(), refreshCharts(), refreshHistory()]);
  }));
  $("worldsDialog").showModal();
};
$("btnCreate").onclick = async (e) => {
  e.preventDefault();
  $("btnCreate").disabled = true;
  try {
    await api("/api/worlds", { name: $("newName").value, seed: $("newSeed").value });
    $("worldsDialog").close();
    applyStatus(await api("/api/status"));
    await loadTerrain(); await Promise.all([loadFrame(), refreshCharts(), refreshHistory()]);
  } finally { $("btnCreate").disabled = false; }
};

// ── close-up mode ─────────────────────────────────────────────
// Zoom down to one small patch of land and watch the people there live
// through the day the simulation just decided for them. Display only:
// nothing seen here changes the world's history.
const cu = { on: false, view: null, prevSpeed: null, tick: -1, base: 7, t0: 0, running: false, loading: false, whoHtml: "" };
const WATCH_SPEED = "1 day/2 min";
const cuHour = () => {
  const daySec = (S.status && S.status.day_seconds) || 120;
  const h = cu.base + (cu.running ? (performance.now() - cu.t0) / 1000 / daySec * 24 : 0);
  return Math.min(23.99, Math.max(0, h));
};
const rebase = (h) => { cu.base = h; cu.t0 = performance.now(); };

async function enterCloseUp(where) {
  if (!CloseUpMod) return;
  if (!cu.view) {
    cu.view = new CloseUpMod.CloseUp($("viewC"), $("cuOverlay"), api);
    window._closeup = cu.view;                 // handy for poking at it from the browser console
    cu.view.onSelect = () => { cu.whoHtml = ""; };
  }
  cu.on = true; cu.prevView = S.view; cu.prevSpeed = null;
  for (const id of ["view3", "view2", "legend"]) $(id).hidden = true;
  for (const id of ["viewC", "cuOverlay", "cuHud", "cuWho"]) $(id).hidden = false;
  document.querySelector(".hint").textContent = "Click a person to follow them · drag to look around · scroll to zoom · Esc to go back";
  const sp = S.status.speeds;
  if (sp.indexOf(S.status.speed) > sp.indexOf("1 day/min")) {           // faster than a day a minute: slow down to watch
    cu.prevSpeed = S.status.speed;
    await control({ action: "speed", speed: WATCH_SPEED });
  }
  cu.tick = S.status.tick; cu.running = S.running;
  rebase(S.running ? 0 : +$("cuHour").value);
  try {
    toast("Walking down to the camps…");
    await cu.view.open(where);
    cu.view.resize();
  } catch (err) {
    console.warn(err); toast("Couldn't open the close-up view."); return exitCloseUp();
  }
  requestAnimationFrame(cuFrame);
}

async function exitCloseUp() {
  if (!cu.on) return;
  cu.on = false;
  if (cu.view) cu.view.close();
  for (const id of ["viewC", "cuOverlay", "cuHud", "cuWho"]) $(id).hidden = true;
  $("legend").hidden = false;
  S.view = cu.prevView || "3d";
  $(S.view === "3d" ? "view3d" : "view2d").click();
  if (cu.prevSpeed) await control({ action: "speed", speed: cu.prevSpeed });
  const p = cu.view && cu.view.selected;
  if (p) showPerson(p);
}

function cuStatus(st) {
  if (st.running !== cu.running) { rebase(cuHour()); cu.running = st.running; }
  if (st.tick !== cu.tick && !cu.loading) {          // a new day has been lived: show it from the start
    cu.tick = st.tick; cu.loading = true;
    cu.view.refresh().then(() => { rebase(0); cu.whoHtml = ""; }).catch(console.warn).finally(() => (cu.loading = false));
  }
}

const hhmm = (h) => `${String(Math.floor(h)).padStart(2, "0")}:${String(Math.floor((h % 1) * 60)).padStart(2, "0")}`;
let lastWho = 0;
function cuFrame() {
  if (!cu.on) return;
  requestAnimationFrame(cuFrame);
  const h = cuHour();
  cu.view.setHour(h);
  cu.view.follow = $("cuFollow").checked;
  const slider = $("cuHour");
  if (document.activeElement !== slider) slider.value = h;
  const sky = h < 5 || h >= 21 ? "night" : h < 7 ? "dawn" : h < 18 ? "day" : "evening";
  $("cuClock").textContent = `${hhmm(h)} · ${sky}`;
  const now = performance.now();
  if (now - lastWho > 300) { lastWho = now; renderWho(h); }
}
$("cuHour").addEventListener("input", (e) => rebase(+e.target.value));
$("cuBack").onclick = exitCloseUp;
window.addEventListener("keydown", (e) => { if (e.code === "Escape" && cu.on) exitCloseUp(); });
$("view3").addEventListener("dblclick", () => { if (S.selected) enterCloseUp({ x: S.selected[0], y: S.selected[1] }); });

function renderWho(h = cuHour()) {
  const v = cu.view, el = $("cuWho");
  const body = v && v.selected && v.people.get(v.selected);
  if (!body) { el.innerHTML = `<div class="muted">No one lives here right now. Find people on the map and try again.</div>`; return; }
  const p = body.userData.data, seg = v.activityOf(p.id);
  let doing = CloseUpMod.DOING[seg.act] || seg.act;
  if (seg.act === "make" && seg.item) doing = `making a ${seg.item.replaceAll("_", " ")}`;
  const log = [
    ...p.thoughts.map((t) => ({ t: t.t, html: `<i>${escapeHtml(t.text)}</i>` })),
    ...p.speech.map((s) => ({ t: s.t, said: true, html: `says <b>«${escapeHtml(s.word)}»</b> <span class="muted">(${escapeHtml(s.gloss)})</span>` })),
  ].filter((x) => x.t <= h).sort((a, b) => a.t - b.t).slice(-12);
  const html = `<div class="nm">${p.name ? escapeHtml(p.name) : "#" + p.id} <span class="muted small">${p.sex === "female" ? "♀" : "♂"} ${Math.floor(p.age)} yrs</span>
      <a href="#" class="small" data-open-person="${p.id}" style="float:right">details</a></div>
    <div class="doing">${escapeHtml(doing)}${p.mind ? ` <span class="muted">· feels ${escapeHtml(p.mind.mood)} · wants to ${escapeHtml(p.mind.goal)}</span>` : ""}</div>
    ${kv([["Health", bar(p.health)], ["Fed", bar(p.energy)], ["Water", bar(p.hydration)],
          ...(p.mind ? [["Joy", bar(p.mind.feelings.joy)], ["Fear", bar(p.mind.feelings.fear)],
                        ["Grief", bar(p.mind.feelings.grief)], ["Loneliness", bar(p.mind.feelings.lonely)]] : [])])}
    ${p.carrying.length ? `<div class="small muted">Carrying ${p.carrying.map((c) => escapeHtml(c.replaceAll("_", " "))).join(", ")}</div>` : ""}
    <ol>${log.map((x) => `<li class="${x.said ? "said" : ""}"><b>${hhmm(x.t)}</b>${x.html}</li>`).join("") || '<li class="muted">…</li>'}</ol>`;
  if (html !== cu.whoHtml) { el.innerHTML = html; cu.whoHtml = html; }
}
$("cuWho").addEventListener("click", (e) => {
  const a = e.target.closest("[data-open-person]");
  if (a) { e.preventDefault(); showPerson(+a.dataset.openPerson); }
});

// ── polling loops ─────────────────────────────────────────────
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
async function loop(fn, msRunning, msPaused) {
  for (;;) {
    try { await fn(); } catch (err) { console.warn(err); }
    await sleep(S.running ? msRunning : msPaused);
  }
}

async function main() {
  if (THREE) init3D();
  else {
    $("view3d").disabled = true; $("view3d").title = "3D library couldn't load (no internet?)";
    $("view2d").click();
  }
  applyStatus(await api("/api/status"));
  await loadTerrain();
  if (THREE) resize();
  await loadFrame();
  loop(async () => {
    const st = await api("/api/status");
    if (st.world.id !== S.worldId) await loadTerrain();
    applyStatus(st);
  }, 500, 1500);
  loop(async () => { if (S.status && S.status.tick !== S.tick) await loadFrame(); }, 250, 1000);
  loop(refreshCharts, 3000, 6000);
  loop(refreshHistory, 3000, 6000);
  loop(refreshInspector, 2000, 4000);
}
main();
