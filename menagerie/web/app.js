// Imported by full URL, with no import map: a host page that has already
// started loading modules ignores import maps, and then nothing runs.
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.170.0/build/three.module.js';
import { compileEngine, loadEngine } from './engine.js';
import { Nursery } from './nursery.js';

const $ = (id) => document.getElementById(id);
const DT = 1 / 60;

// ---------------------------------------------------------------- habitats

const HABITATS = {
  sprint: {
    title: 'Sprint',
    brief: 'Ten seconds on a flat floor. Score is distance covered, in metres.',
    unit: 'm',
    metric: 'distance',
  },
  walk: {
    title: 'Walk',
    brief: 'A sprint for things with legs: the run ends the moment more than two fifths of the body is resting on the floor.',
    unit: 'm',
    metric: 'distance',
  },
  rough: {
    title: 'Rough',
    brief: 'Twelve seconds over lumpy ground, on two different courses. Score is distance.',
    unit: 'm',
    metric: 'distance',
  },
  chase: {
    title: 'Chase',
    brief: 'Flags pop up in turn, each in a new direction. Score is ground gained on them over three courses.',
    unit: 'm',
    metric: 'gained',
  },
  shove: {
    title: 'Shove',
    brief: 'An 80 kg crate sits just ahead. Score is how far the crate has gone after ten seconds.',
    unit: 'm',
    metric: 'crate moved',
  },
  swim: {
    title: 'Swim',
    brief: 'Weightless in thick water with nothing to push off but the water. Score is distance.',
    unit: 'm',
    metric: 'distance',
  },
  jump: {
    title: 'Jump',
    brief: 'Five seconds to get the whole body off the floor. Score is the height of the lowest part at its peak.',
    unit: 'm',
    metric: 'clearance',
  },
};
// Walk first: it is what the page opens on, and its animals are the ones
// that look most like animals.
const ORDER = ['walk', 'sprint', 'rough', 'chase', 'shove', 'swim', 'jump'];
// What each axis of the map means, by the trait the archive was sorted on.
const AXIS = {
  feet: 'more feet',
  tiptoe: 'higher off the ground',
  parts: 'more body parts',
  spread: 'more sprawling',
  stature: 'stands taller',
  airborne: 'more time in the air',
};
const TRIALS = { chase: 3, rough: 2 };
const SECONDS = { sprint: 10, walk: 10, rough: 12, swim: 10, chase: 14, jump: 5, shove: 10 };
const RING = 4; // sumo ring radius, metres
const CRATE = { half: 0.4, mass: 80, gap: 0.6 };

// ------------------------------------------------------------------- names

// Linnaean names from the body: genus from the part count and build,
// species from how it moves. Deterministic, so a creature keeps its name.
const COUNT = ['', '', 'Di', 'Tri', 'Tetra', 'Penta', 'Hexa', 'Hepta', 'Octo', 'Ennea', 'Deca', 'Hendeca', 'Dodeca', 'Trideca', 'Tetradeca'];
const BUILD_LOW = ['herpes', 'reptus', 'placus', 'serpens'];
const BUILD_MID = ['pus', 'melus', 'soma', 'scelis'];
const BUILD_TALL = ['stylus', 'gradus', 'bates', 'dromus'];
const SPECIES = {
  sprint: ['velox', 'cursor', 'properans', 'celer', 'festinans', 'citatus'],
  walk: ['ambulans', 'gradiens', 'incedens', 'pedester', 'viator', 'spatians'],
  rough: ['saxatilis', 'montanus', 'scandens', 'asper', 'clivorum', 'rupestris'],
  chase: ['venator', 'sequax', 'indagator', 'vestigans', 'persecutor', 'quaeritans'],
  shove: ['trudens', 'impulsor', 'pulsator', 'arietans', 'propellens', 'protrusor'],
  swim: ['natans', 'pelagicus', 'undulans', 'remigans', 'fluitans', 'nectonicus'],
  jump: ['saltator', 'saliens', 'exsiliens', 'subsultans', 'volitans', 'pulex'],
};
function hash(str) {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) h = Math.imul(h ^ str.charCodeAt(i), 16777619);
  return h >>> 0;
}
function nameOf(elite, task) {
  const h = hash(task + ':' + elite.cell.join(','));
  const e = elite.eval;
  const lift = task === 'swim' ? (e.spread - 0.5) / 1.2 : e.tiptoe ?? e.stature;
  const builds = lift < 0.3 ? BUILD_LOW : lift < 0.62 ? BUILD_MID : BUILD_TALL;
  const stem = builds[h % builds.length];
  let genus = COUNT[Math.min(e.parts, COUNT.length - 1)] + stem;
  genus = genus.replace(/aa|ao/g, (m) => m[0]).replace(/([aeio])\1/g, '$1');
  const sp = SPECIES[task][(h >>> 8) % SPECIES[task].length];
  return `${genus} ${sp}`;
}
function commonOf(elite, task) {
  const e = elite.eval;
  const kg = e.mass >= 100 ? Math.round(e.mass) : e.mass.toFixed(1);
  let gait;
  const fam = elite.family === undefined ? '' : `, family ${ROMAN[elite.family] || elite.family + 1}`;
  if (task === 'swim') return `${e.parts}-part ${e.spread > 1.0 ? 'sprawling' : 'compact'} swimmer, ${kg} kg${fam}`;
  if (task === 'jump') gait = 'jumper';
  else if (e.airborne > 0.2) gait = 'bounder';
  else if (e.tiptoe < 0.3) gait = 'crawler';
  else if (e.tiptoe < 0.62) gait = 'scuttler';
  else gait = 'strider';
  const feet = e.feet === 1 ? 'one-footed' : `${e.feet}-footed`;
  return `${feet} ${gait}, ${e.parts} parts, ${kg} kg${fam}`;
}

// ------------------------------------------------------------------- scene

const canvas = $('view');
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, powerPreference: 'high-performance' });
renderer.shadowMap.enabled = true;
renderer.shadowMap.type = THREE.PCFSoftShadowMap;
renderer.toneMapping = THREE.ACESFilmicToneMapping;
renderer.toneMappingExposure = 1.05;
const scene = new THREE.Scene();
const camera = new THREE.PerspectiveCamera(38, 1, 0.1, 400);

const hemi = new THREE.HemisphereLight(0xffffff, 0x888888, 1.0);
scene.add(hemi);
const sun = new THREE.DirectionalLight(0xffffff, 2.4);
sun.castShadow = true;
sun.shadow.mapSize.set(2048, 2048);
sun.shadow.bias = -0.0004;
sun.shadow.normalBias = 0.02;
scene.add(sun, sun.target);

const world3 = new THREE.Group(); // terrain and props for the current habitat
const actors3 = new THREE.Group();
scene.add(world3, actors3);

let theme = {};
function cssColor(name) {
  return new THREE.Color(getComputedStyle(document.documentElement).getPropertyValue(name).trim() || '#888');
}
function readTheme() {
  const dark = matchMedia('(prefers-color-scheme: dark)').matches;
  const forced = document.documentElement.dataset.theme;
  theme = {
    dark: forced ? forced === 'dark' : dark,
    sky: cssColor('--sky'),
    ground: cssColor('--ground'),
    grid: cssColor('--grid'),
    ink: cssColor('--ink'),
    accent: cssColor('--accent'),
    water: cssColor('--water'),
    waterDeep: cssColor('--water-deep'),
    panel: cssColor('--panel'),
  };
  hemi.intensity = theme.dark ? 0.55 : 1.05;
  sun.intensity = theme.dark ? 1.7 : 2.3;
}

// Ground texture: one-metre squares, heavier line every five.
function gridTexture() {
  const s = 512;
  const c = document.createElement('canvas');
  c.width = c.height = s;
  const g = c.getContext('2d');
  g.fillStyle = '#' + theme.ground.getHexString();
  g.fillRect(0, 0, s, s);
  const line = '#' + theme.grid.getHexString();
  g.strokeStyle = line;
  const cell = s / 5;
  for (let i = 0; i <= 5; i++) {
    g.globalAlpha = i === 0 || i === 5 ? 0.9 : 0.38;
    g.lineWidth = i === 0 || i === 5 ? 4 : 1.5;
    g.beginPath();
    g.moveTo(i * cell, 0);
    g.lineTo(i * cell, s);
    g.moveTo(0, i * cell);
    g.lineTo(s, i * cell);
    g.stroke();
  }
  const t = new THREE.CanvasTexture(c);
  t.wrapS = t.wrapT = THREE.RepeatWrapping;
  t.anisotropy = renderer.capabilities.getMaxAnisotropy();
  t.colorSpace = THREE.SRGBColorSpace;
  return t;
}

function textSprite(text, { size = 0.5, color = null } = {}) {
  const c = document.createElement('canvas');
  c.width = 256;
  c.height = 128;
  const g = c.getContext('2d');
  g.font = '500 84px "IBM Plex Mono", ui-monospace, monospace';
  g.textAlign = 'center';
  g.textBaseline = 'middle';
  g.fillStyle = '#' + (color || theme.grid).getHexString();
  g.fillText(text, 128, 68);
  const t = new THREE.CanvasTexture(c);
  t.colorSpace = THREE.SRGBColorSpace;
  const m = new THREE.Mesh(
    new THREE.PlaneGeometry(size * 2, size),
    new THREE.MeshBasicMaterial({ map: t, transparent: true, depthWrite: false })
  );
  return m;
}

function disposeGroup(group) {
  group.traverse((o) => {
    if (o.geometry) o.geometry.dispose();
    if (o.material) {
      for (const m of [].concat(o.material)) {
        if (m.map) m.map.dispose();
        m.dispose();
      }
    }
  });
  group.clear();
}

let particles = null;
function buildHabitat(terrain, task, lanes) {
  disposeGroup(world3);
  particles = null;
  const water = terrain.kind === 'water';
  const bg = water ? theme.water : theme.sky;
  scene.background = bg.clone();
  scene.fog = new THREE.Fog(bg.clone(), water ? 14 : 30, water ? 60 : 110);

  if (water) {
    // Motes hanging in the water, so movement reads against something.
    const n = 1400;
    const pos = new Float32Array(n * 3);
    let seed = 7;
    const rnd = () => ((seed = (seed * 16807) % 2147483647) / 2147483647);
    for (let i = 0; i < n; i++) {
      pos[i * 3] = (rnd() - 0.5) * 50;
      pos[i * 3 + 1] = (rnd() - 0.5) * 24;
      pos[i * 3 + 2] = rnd() * 70 - 12;
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(pos, 3));
    particles = new THREE.Points(
      g,
      new THREE.PointsMaterial({ color: theme.ink, size: 0.07, transparent: true, opacity: theme.dark ? 0.45 : 0.3, sizeAttenuation: true })
    );
    world3.add(particles);
    // Distance rings to swim through.
    for (let z = 5; z <= 40; z += 5) {
      const ring = new THREE.Mesh(
        new THREE.TorusGeometry(2.2, 0.025, 6, 64),
        new THREE.MeshBasicMaterial({ color: theme.grid, transparent: true, opacity: 0.8 })
      );
      ring.position.set(0, 0, z);
      world3.add(ring);
      const label = textSprite(`${z}`, { size: 0.45 });
      label.position.set(0, 2.55, z);
      label.rotation.y = Math.PI;
      world3.add(label);
    }
    return;
  }

  const tex = gridTexture();
  const mat = new THREE.MeshStandardMaterial({ map: tex, roughness: 0.95, metalness: 0 });
  if (terrain.kind === 'disc') {
    // The ring: a raised platform with a painted edge, floor a metre below.
    tex.repeat.set(80, 80);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat);
    floor.rotation.x = -Math.PI / 2;
    floor.position.y = -1;
    floor.receiveShadow = true;
    const ringTex = gridTexture();
    ringTex.repeat.set((terrain.radius * 2) / 5, (terrain.radius * 2) / 5);
    const top = new THREE.Mesh(
      new THREE.CylinderGeometry(terrain.radius, terrain.radius, 1, 72),
      [new THREE.MeshStandardMaterial({ color: theme.grid, roughness: 0.9 }), new THREE.MeshStandardMaterial({ map: ringTex, roughness: 0.95 }), new THREE.MeshStandardMaterial({ color: theme.grid })]
    );
    top.position.y = -0.5;
    top.receiveShadow = true;
    top.castShadow = true;
    const edge = new THREE.Mesh(new THREE.RingGeometry(terrain.radius - 0.12, terrain.radius, 96), new THREE.MeshBasicMaterial({ color: theme.accent }));
    edge.rotation.x = -Math.PI / 2;
    edge.position.y = 0.012;
    world3.add(floor, top, edge);
    return;
  }
  if (terrain.kind === 'heights') {
    // Far field, flat.
    tex.repeat.set(80, 80);
    const far = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat);
    far.rotation.x = -Math.PI / 2;
    far.position.y = -0.002;
    far.receiveShadow = true;
    world3.add(far);
    const { nx, nz, size, centre, heights } = terrain;
    const g = new THREE.PlaneGeometry(size[0], size[1], nx - 1, nz - 1);
    g.rotateX(-Math.PI / 2);
    const p = g.attributes.position;
    const uv = g.attributes.uv;
    for (let iz = 0; iz < nz; iz++) {
      for (let ix = 0; ix < nx; ix++) {
        const i = iz * nx + ix;
        // PlaneGeometry rows run +z-ward after the rotation; match the sim,
        // whose rows also run from -z to +z.
        p.setY(i, heights[i]);
        const x = centre[0] + size[0] * (ix / (nx - 1) - 0.5);
        const z = centre[1] + size[1] * (iz / (nz - 1) - 0.5);
        p.setX(i, x);
        p.setZ(i, z);
        uv.setXY(i, x / 5, z / 5);
      }
    }
    g.computeVertexNormals();
    const hillTex = gridTexture();
    const hill = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ map: hillTex, roughness: 0.95 }));
    hill.receiveShadow = true;
    world3.add(hill);
  } else {
    tex.repeat.set(80, 80);
    const floor = new THREE.Mesh(new THREE.PlaneGeometry(400, 400), mat);
    floor.rotation.x = -Math.PI / 2;
    floor.receiveShadow = true;
    world3.add(floor);
  }

  if (task === 'sprint' || task === 'rough') {
    // Distance markers down the course.
    for (let z = 5; z <= 60; z += 5) {
      const label = textSprite(`${z}`, { size: 0.9 });
      label.rotation.x = -Math.PI / 2;
      label.rotation.z = Math.PI;
      label.position.set(-(lanes.min - 1.6), 0.012 + (terrain.kind === 'heights' ? 0.5 : 0), z);
      if (terrain.kind !== 'heights') world3.add(label);
    }
    const start = new THREE.Mesh(
      new THREE.PlaneGeometry(lanes.max - lanes.min + 3, 0.06),
      new THREE.MeshBasicMaterial({ color: theme.accent })
    );
    start.rotation.x = -Math.PI / 2;
    start.position.set((lanes.max + lanes.min) / 2, 0.011, 0);
    if (terrain.kind !== 'heights') world3.add(start);
  }
  if (task === 'jump') {
    // A measuring staff behind the jumper.
    const staff = new THREE.Group();
    const pole = new THREE.Mesh(new THREE.BoxGeometry(0.05, 3, 0.05), new THREE.MeshStandardMaterial({ color: theme.grid }));
    pole.position.y = 1.5;
    staff.add(pole);
    for (let i = 0; i <= 12; i++) {
      const y = i * 0.25;
      const tick = new THREE.Mesh(
        new THREE.BoxGeometry(i % 4 === 0 ? 0.5 : 0.25, 0.02, 0.02),
        new THREE.MeshBasicMaterial({ color: i % 4 === 0 ? theme.accent : theme.grid })
      );
      tick.position.set(0, y, 0);
      staff.add(tick);
      if (i % 4 === 0 && i > 0) {
        const l = textSprite(`${y}`, { size: 0.3, color: theme.ink });
        l.position.set(0.55, y, 0);
        l.rotation.y = Math.PI;
        staff.add(l);
      }
    }
    staff.position.set(1.8, 0, -1.2);
    world3.add(staff);
  }
}

// Crates the creatures push around.
const crates3 = new THREE.Group();
scene.add(crates3);
function syncCrates(world) {
  const n = world ? world.crates : 0;
  while (crates3.children.length > n) {
    const m = crates3.children[crates3.children.length - 1];
    crates3.remove(m);
    for (const child of m.children) {
      child.geometry.dispose();
      child.material.dispose();
    }
    m.geometry.dispose();
    m.material.dispose();
  }
  for (let i = 0; i < n; i++) {
    const c = world.crate(i);
    let m = crates3.children[i];
    if (!m) {
      m = new THREE.Mesh(
        new THREE.BoxGeometry(c[7] * 2, c[8] * 2, c[9] * 2),
        new THREE.MeshStandardMaterial({ color: theme.accent, roughness: 0.8 })
      );
      m.castShadow = true;
      m.receiveShadow = true;
      // Strapping, so it reads as a crate and its tumbling is visible.
      const edges = new THREE.LineSegments(new THREE.EdgesGeometry(m.geometry), new THREE.LineBasicMaterial({ color: theme.ink }));
      m.add(edges);
      crates3.add(m);
    }
    m.position.set(c[0], c[1], c[2]);
    m.quaternion.set(c[3], c[4], c[5], c[6]);
  }
}

// Goal flag.
const flag = new THREE.Group();
{
  const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.025, 0.025, 1.6, 8), new THREE.MeshStandardMaterial({ color: 0x888888 }));
  pole.position.y = 0.8;
  pole.castShadow = true;
  const cloth = new THREE.Mesh(new THREE.PlaneGeometry(0.55, 0.34), new THREE.MeshStandardMaterial({ color: 0xffaa00, side: THREE.DoubleSide }));
  cloth.position.set(0.29, 1.4, 0);
  cloth.castShadow = true;
  const ring = new THREE.Mesh(new THREE.RingGeometry(0.82, 0.9, 48), new THREE.MeshBasicMaterial({ color: 0xffaa00, transparent: true, opacity: 0.8 }));
  ring.rotation.x = -Math.PI / 2;
  ring.position.y = 0.012;
  flag.add(pole, cloth, ring);
  flag.userData = { pole, cloth, ring };
  flag.visible = false;
  scene.add(flag);
}

// ------------------------------------------------------------------ actors

const _q = new THREE.Quaternion();
const _v = new THREE.Vector3();

/** A box with its edges and corners rounded off to radius `r`. */
function roundedBox(w, h, d, r) {
  const g = new THREE.BoxGeometry(w, h, d, 4, 4, 4);
  const half = [w / 2, h / 2, d / 2];
  const pos = g.attributes.position;
  const nor = g.attributes.normal;
  const p = [0, 0, 0];
  const c = [0, 0, 0];
  for (let i = 0; i < pos.count; i++) {
    p[0] = pos.getX(i);
    p[1] = pos.getY(i);
    p[2] = pos.getZ(i);
    let len = 0;
    for (let k = 0; k < 3; k++) {
      const inner = half[k] - r;
      // Move the quarter-way rows out to where the rounding starts, so
      // faces stay flat right up to the fillet.
      if (Math.abs(Math.abs(p[k]) - half[k] / 2) < 1e-6) p[k] = Math.sign(p[k]) * inner;
      // Each point sits `r` out from the nearest point of the inner box.
      c[k] = Math.max(-inner, Math.min(inner, p[k]));
      len += (p[k] - c[k]) ** 2;
    }
    len = Math.sqrt(len) || 1;
    const n = [(p[0] - c[0]) / len, (p[1] - c[1]) / len, (p[2] - c[2]) / len];
    pos.setXYZ(i, c[0] + n[0] * r, c[1] + n[1] * r, c[2] + n[2] * r);
    nor.setXYZ(i, n[0], n[1], n[2]);
  }
  return g;
}

class Actor {
  constructor(world, c, { dim = false, avoidHue = null, dx = 0 } = {}) {
    this.world = world;
    this.c = c;
    // Drawn this far to the side of where it is simulated (see lanes).
    this.dx = dx;
    this.group = new THREE.Group();
    const shapes = world.shapes(c);
    const st = world.state(c);
    this.hue = st.hue;
    // Opponents need telling apart: if this one's colour is close to the
    // other's, move it across the wheel.
    if (avoidHue !== null) {
      const d = Math.abs(((this.hue - avoidHue + 1.5) % 1) - 0.5);
      if (d < 0.17) this.hue = (avoidHue + 0.45) % 1;
    }
    this.meshes = [];
    const n = shapes.length / 8;
    let maxDepth = 1;
    for (let i = 0; i < n; i++) maxDepth = Math.max(maxDepth, shapes[i * 8 + 3]);
    for (let i = 0; i < n; i++) {
      const [hx, hy, hz, depth, flip, , parent, r] = shapes.subarray(i * 8, i * 8 + 8);
      const geo = roundedBox(hx * 2, hy * 2, hz * 2, Math.min(r * 1.6, 0.45 * Math.min(hx, hy, hz)));
      const col = new THREE.Color().setHSL(
        (this.hue + depth * 0.035) % 1,
        dim ? 0.25 : 0.62,
        (theme.dark ? 0.5 : 0.46) + 0.2 * (depth / (maxDepth + 1)) - (flip ? 0.035 : 0)
      );
      const mat = new THREE.MeshStandardMaterial({ color: col, roughness: 0.55, metalness: 0.02, emissive: col.clone(), emissiveIntensity: 0 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      if (parent >= 0) {
        // A ball at the hinge, so joints read as joints.
        const ball = new THREE.Mesh(
          new THREE.SphereGeometry(Math.min(hx, hz) * 0.72, 14, 10),
          new THREE.MeshStandardMaterial({ color: col.clone().multiplyScalar(0.55), roughness: 0.7 })
        );
        ball.position.set(0, -hy, 0);
        ball.castShadow = true;
        mesh.add(ball);
      } else {
        this.addEyes(mesh, hx, hy, hz);
      }
      this.group.add(mesh);
      this.meshes.push(mesh);
    }
    this.com = new THREE.Vector3();
    this.halves = shapes;
    this.size = Math.cbrt(shapes.reduce((a, _, i) => (i % 8 === 0 ? a + 8 * shapes[i] * shapes[i + 1] * shapes[i + 2] : a), 0));
    actors3.add(this.group);
    this.trail = null;
    this.sync();
    // Radius of a ball around the centre of mass that holds the rest pose.
    this.radius = 0;
    for (let i = 0; i < n; i++) {
      const h = Math.hypot(shapes[i * 8], shapes[i * 8 + 1], shapes[i * 8 + 2]);
      this.radius = Math.max(this.radius, this.meshes[i].position.distanceTo(this.com) + h);
    }
  }

  addEyes(mesh, hx, hy, hz) {
    // Two eyes on the face that points down the course at the start.
    const r = Math.min(hx, hy, 0.5) * 0.3;
    this.pupils = [];
    for (const s of [-1, 1]) {
      const eye = new THREE.Mesh(new THREE.SphereGeometry(r, 16, 12), new THREE.MeshStandardMaterial({ color: 0xf6f6f0, roughness: 0.3 }));
      eye.position.set(s * Math.min(hx * 0.5, r * 1.9), hy * 0.35, hz + r * 0.25);
      const pupil = new THREE.Mesh(new THREE.SphereGeometry(r * 0.5, 12, 10), new THREE.MeshBasicMaterial({ color: 0x101414 }));
      pupil.position.set(0, 0, r * 0.68);
      eye.add(pupil);
      mesh.add(eye);
      this.pupils.push({ pupil, r });
    }
  }

  sync() {
    const t = this.world.transforms(this.c);
    for (let i = 0; i < this.meshes.length; i++) {
      const o = i * 8;
      const m = this.meshes[i];
      m.position.set(t[o] + this.dx, t[o + 1], t[o + 2]);
      m.quaternion.set(t[o + 3], t[o + 4], t[o + 5], t[o + 6]);
      m.material.emissiveIntensity = 0.22 * t[o + 7];
    }
    const st = this.world.state(this.c);
    st.goal[0] += this.dx;
    this.com.set(st.com[0] + this.dx, st.com[1], st.com[2]);
    this.vel = st.vel;
    this.exploded = st.exploded;
    this.goal = st.goal;
    if (this.pupils) {
      // Eyes follow the goal.
      _v.set(st.goal[0], st.goal[1], st.goal[2]).sub(this.meshes[0].position);
      _q.copy(this.meshes[0].quaternion).invert();
      _v.applyQuaternion(_q).normalize();
      for (const { pupil, r } of this.pupils) {
        pupil.position.set(_v.x * r * 0.42, _v.y * r * 0.42, r * 0.68);
      }
    }
    if (this.trail) this.trail.push(this.com);
  }

  addTrail(underwater) {
    this.trail = new Trail(underwater, new THREE.Color().setHSL(this.hue, 0.6, theme.dark ? 0.6 : 0.4));
  }

  dispose() {
    actors3.remove(this.group);
    disposeGroup(this.group);
    if (this.trail) this.trail.dispose();
  }
}

class Trail {
  constructor(underwater, color) {
    this.max = 900;
    this.n = 0;
    this.underwater = underwater;
    this.pos = new Float32Array(this.max * 3);
    this.geo = new THREE.BufferGeometry();
    this.geo.setAttribute('position', new THREE.BufferAttribute(this.pos, 3));
    this.line = new THREE.Line(this.geo, new THREE.LineBasicMaterial({ color, transparent: true, opacity: 0.75 }));
    this.line.frustumCulled = false;
    this.last = new THREE.Vector3(1e9, 0, 0);
    scene.add(this.line);
  }
  push(p) {
    const y = this.underwater ? p.y : 0.015;
    if (Math.hypot(p.x - this.last.x, p.z - this.last.z, this.underwater ? p.y - this.last.y : 0) < 0.04) return;
    this.last.copy(p);
    if (this.n === this.max) {
      this.pos.copyWithin(0, 3);
      this.n--;
    }
    this.pos.set([p.x, y, p.z], this.n * 3);
    this.n++;
    this.geo.setDrawRange(0, this.n);
    this.geo.attributes.position.needsUpdate = true;
  }
  dispose() {
    scene.remove(this.line);
    this.geo.dispose();
    this.line.material.dispose();
  }
}

// ------------------------------------------------------------------ camera

const cam = {
  target: new THREE.Vector3(0, 0.5, 0),
  want: new THREE.Vector3(0, 0.5, 0),
  dist: 7,
  wantDist: 7,
  yaw: 2.45,
  pitch: 0.36,
  snap: true,
};
function updateCamera(dt) {
  const k = cam.snap ? 1 : 1 - Math.exp(-dt * 4.5);
  cam.target.lerp(cam.want, k);
  cam.dist += (cam.wantDist - cam.dist) * (cam.snap ? 1 : 1 - Math.exp(-dt * 3));
  cam.snap = false;
  const cp = Math.cos(cam.pitch);
  camera.position.set(
    cam.target.x + cam.dist * cp * Math.sin(cam.yaw),
    cam.target.y + cam.dist * Math.sin(cam.pitch),
    cam.target.z + cam.dist * cp * Math.cos(cam.yaw)
  );
  camera.lookAt(cam.target);
  sun.position.set(cam.target.x + 7, cam.target.y + 16, cam.target.z - 6);
  sun.target.position.copy(cam.target);
  const r = Math.max(6, cam.dist * 0.9);
  const sc = sun.shadow.camera;
  if (sc.right !== r) {
    sc.left = -r;
    sc.right = r;
    sc.top = r;
    sc.bottom = -r;
    sc.near = 1;
    sc.far = 60;
    sc.updateProjectionMatrix();
  }
}

// The stacked (phone) layout, as opposed to panels floating over the view.
const stackedQuery = matchMedia('(max-width: 760px), (max-height: 520px)');

/**
 * Camera distance at which something `halfWidth` metres either side of the
 * target fits in the part of the picture the panels leave clear.
 */
function fitDistance(halfWidth) {
  const w = canvas.clientWidth || 1;
  const h = canvas.clientHeight || 1;
  let halfPx = w / 2;
  if (!stackedQuery.matches) {
    // The picture is slid right to clear the drawer (see resize()).
    const off = Math.min(170, w * 0.13);
    halfPx = Math.max(120, Math.min(w / 2 + off - 350, w / 2 - off));
  }
  const tanV = Math.tan((camera.fov * Math.PI) / 360);
  return (1.06 * halfWidth * h) / (2 * halfPx * tanV);
}

// Pointer: drag orbits, wheel and pinch zoom, a tap aims (in Roam).
const pointers = new Map();
let dragMoved = 0;
let pinch = 0;
canvas.addEventListener('pointerdown', (e) => {
  canvas.setPointerCapture(e.pointerId);
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
  dragMoved = 0;
  if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    pinch = Math.hypot(a[0] - b[0], a[1] - b[1]);
  }
  canvas.classList.add('dragging');
});
canvas.addEventListener('pointermove', (e) => {
  const p = pointers.get(e.pointerId);
  if (!p) return;
  const dx = e.clientX - p[0];
  const dy = e.clientY - p[1];
  pointers.set(e.pointerId, [e.clientX, e.clientY]);
  if (pointers.size === 1) {
    dragMoved += Math.abs(dx) + Math.abs(dy);
    cam.yaw -= dx * 0.006;
    cam.pitch = Math.min(1.45, Math.max(stage.underwater ? -1.2 : 0.04, cam.pitch + dy * 0.005));
  } else if (pointers.size === 2) {
    const [a, b] = [...pointers.values()];
    const d = Math.hypot(a[0] - b[0], a[1] - b[1]);
    if (pinch > 0) cam.wantDist = Math.min(60, Math.max(2, cam.wantDist * (pinch / d)));
    pinch = d;
    dragMoved += 10;
  }
});
function endPointer(e) {
  if (!pointers.has(e.pointerId)) return;
  pointers.delete(e.pointerId);
  canvas.classList.remove('dragging');
  if (dragMoved < 6 && e.type === 'pointerup') stage.tap(e);
}
canvas.addEventListener('pointerup', endPointer);
canvas.addEventListener('pointercancel', endPointer);
canvas.addEventListener(
  'wheel',
  (e) => {
    e.preventDefault();
    cam.wantDist = Math.min(60, Math.max(2, cam.wantDist * Math.exp(e.deltaY * 0.0012)));
  },
  { passive: false }
);

// ------------------------------------------------------------------- stage

// The stage owns the simulated world on show and knows the four ways of
// looking at a creature.
/**
 * Step an open world until its creatures have come to rest and its clock
 * has started, without drawing any of it: the same settling a scored trial
 * does before it begins.
 */
function settle(world) {
  let guard = 0;
  do world.step(1);
  while (world.time < 0 && guard++ < 400);
}

const stage = {
  eng: null,
  // Race and lineage give every creature a world of its own, stepped in
  // lockstep: each then starts from exactly the pose its trial started
  // from, which gaits turn out to be touchy about. `world` is the first.
  worlds: [],
  world: null,
  actors: [],
  tags: [],
  mode: 'watch',
  task: 'sprint',
  elite: null,
  archive: null,
  trial: 0,
  hold: 0,
  speed: 1,
  paused: false,
  acc: 0,
  underwater: false,
  userGoal: false,
  goalsHit: 0,
  ancestor: -1,
  focus: 0,
  exhibit: null,
  rival: null, // { elite, task }: who the selected creature fights
  result: null, // sumo: index of the winner, or 'draw'
  resultAt: 0,
  swap: false,
  crateStart: null,

  clear() {
    for (const a of this.actors) a.dispose();
    this.actors = [];
    for (const w of this.worlds) w.free();
    this.worlds = [];
    this.world = null;
    $('tags').replaceChildren();
    this.tags = [];
    flag.visible = false;
    syncCrates(null);
  },

  /** Who the selected creature meets in the ring. */
  rivalFor() {
    if (this.rival && this.rival.elite !== this.elite) return this.rival;
    const others = this.archive.elites.filter((e) => e !== this.elite).sort((a, b) => b.fitness - a.fitness);
    return { elite: others[0] || this.elite, task: this.task };
  },

  /** Is there anyone other than itself for it to fight? */
  hasRival() {
    return !!this.elite && this.rivalFor().elite !== this.elite;
  },

  /** (Re)build the world for the current task, elite and mode. */
  start({ keepCamera = false } = {}) {
    this.clear();
    const { eng, task, mode } = this;
    const elite = this.elite;
    if (!elite && !this.exhibit) return;
    let lanes = { min: 0, max: 0 };
    this.hold = 0;
    this.acc = 0;
    this.userGoal = false;
    this.goalsHit = 0;
    this.focus = 0;
    this.underwater = task === 'swim' && mode !== 'fight';
    this.result = null;
    this.crateStart = null;

    if (this.exhibit) {
      this.world = eng.legacyEpisode(this.exhibit, 'sprint');
      this.worlds = [this.world];
      this.actors.push(new Actor(this.world, 0));
    } else if (mode === 'watch') {
      const genome = this.ancestor >= 0 ? this.lineage()[this.ancestor].genome : elite.genome;
      this.world = eng.episode(genome, task, this.trial);
      this.worlds = [this.world];
      this.actors.push(new Actor(this.world, 0));
    } else if (mode === 'fight') {
      // Two creatures, nose to nose on a raised ring, each told the
      // other is where it wants to go.
      this.world = eng.arena(RING);
      this.worlds = [this.world];
      const me = { elite, task };
      const pair = this.swap ? [this.rivalFor(), me] : [me, this.rivalFor()];
      pair.forEach((f, i) => this.world.add(f.elite.genome, 0, 0, i === 0 ? -RING * 0.55 : RING * 0.55, i === 0 ? 0 : Math.PI));
      settle(this.world);
      pair.forEach((f, c) => {
        // The selected creature keeps its own colour whichever corner it
        // is in; the rival moves away from it on the colour wheel if close.
        this.actors.push(new Actor(this.world, c, { avoidHue: f === me ? null : elite.genome.hue }));
        const el = document.createElement('div');
        el.className = 'tag';
        el.textContent = nameOf(f.elite, f.task);
        $('tags').append(el);
        this.tags.push(el);
      });
      this.focus = this.swap ? 1 : 0;
    } else {
      let entries;
      if (mode === 'roam') {
        entries = [{ genome: elite.genome, tag: null }];
      } else if (mode === 'line') {
        const line = this.lineage();
        const picks = pickEvenly(line.length, stackedQuery.matches ? 5 : 7);
        entries = picks.map((i) => ({
          genome: line[i].genome,
          tag: i === 0 ? 'founder' : i === line.length - 1 ? 'today' : `gen ${line[i].depth}`,
        }));
      } else {
        // The champion of each family where there are families; otherwise
        // the best of each row of the map, so the line-up isn't all cousins.
        let top = this.archive.racers && this.archive.racers();
        if (!top) {
          const rows = new Map();
          for (const e of this.archive.elites) {
            const b = rows.get(e.cell[1]);
            if (!b || e.fitness > b.fitness) rows.set(e.cell[1], e);
          }
          top = [...rows.values()];
        }
        // Slowest on the left, fastest on the right, clear of the drawer.
        top = [...top].sort((a, b) => b.fitness - a.fitness).slice(0, 8).reverse();
        entries = top.map((e) => ({
          genome: e.genome,
          tag: e.family === undefined ? nameOf(e, task).split(' ')[0] : `${ROMAN[e.family]} · ${nameOf(e, task).split(' ')[0]}`,
          mine: e === elite,
        }));
      }
      const gap = task === 'swim' ? 3.0 : 2.6;
      const n = entries.length;
      entries.forEach((en, i) => {
        const x = (i - (n - 1) / 2) * gap;
        // Lanes run left to right as seen from behind the start line.
        // Each runs down the middle of its own world, exactly where its
        // trial ran, and is only drawn in its lane: even moving a creature
        // sideways changes the arithmetic enough to trip a touchy gait.
        // Rough ground is the exception, since a creature drawn off to
        // the side would no longer match the hills under it.
        const real = task === 'rough' && n > 1;
        const w = eng.world(task, { trial: this.trial });
        this.worlds.push(w);
        w.add(en.genome, real ? -x : 0, 0, 0, 0);
        settle(w);
        this.actors.push(new Actor(w, 0, { dx: real ? 0 : -x }));
        if (en.tag) {
          const el = document.createElement('div');
          el.className = 'tag';
          el.textContent = en.tag;
          $('tags').append(el);
          this.tags.push(el);
        }
        if (en.mine || (mode === 'line' && i === n - 1)) this.focus = i;
      });
      this.world = this.worlds[0];
      lanes = { min: -((n - 1) / 2) * gap, max: ((n - 1) / 2) * gap };
      if (mode === 'roam' && task === 'chase') this.nextChaseGoal();
      if (mode === 'roam' && task === 'shove') {
        const z = this.world.front(0) + CRATE.gap + CRATE.half;
        this.world.addCrate(0, CRATE.half + 0.01, z, CRATE.half, CRATE.mass);
      }
    }
    if (mode === 'watch' || mode === 'roam') this.actors[0].addTrail(this.underwater);
    syncCrates(this.world);
    if (this.world.crates) this.crateStart = Float32Array.from(this.world.crate(0).subarray(0, 3));

    buildHabitat(this.world.terrain(), mode === 'fight' ? 'sumo' : task, lanes);
    const a = this.actors[this.focus];
    if (!keepCamera) {
      const many = this.actors.length > 1;
      cam.wantDist = many ? Math.max(10, fitDistance(lanes.max + 2.6)) : Math.max(2.4, a.radius * 4.4);
      if (task === 'jump' && !many) cam.wantDist *= 1.25;
      cam.yaw = many ? 2.75 : 2.45;
      cam.pitch = many ? 0.62 : this.underwater ? 0.22 : 0.34;
      if (mode === 'fight') {
        cam.wantDist = Math.max(11, fitDistance(RING + 0.7));
        cam.yaw = 1.2;
        cam.pitch = 0.42;
      }
      cam.snap = true;
    }
    this.aim();
    canvas.classList.toggle('aiming', mode === 'roam');
  },

  lineage() {
    return this.archive.lineageOf(this.elite);
  },

  hasLineage() {
    return !!this.elite && this.lineage().length > 2;
  },

  nextChaseGoal() {
    const seq = [0, 90, -90, 180, 45, -135, -70, 60, 170, -20];
    const h = (seq[this.goalsHit % seq.length] * Math.PI) / 180;
    const c = this.actors[0].com;
    this.world.setGoal(0, c.x + Math.sin(h) * 7, 0, c.z + Math.cos(h) * 7);
  },

  tap(e) {
    if (this.mode !== 'roam' || !this.world) return;
    const rect = canvas.getBoundingClientRect();
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1);
    const ray = new THREE.Raycaster();
    ray.setFromCamera(ndc, camera);
    const hit = new THREE.Vector3();
    if (this.underwater) {
      // Aim along the view ray, about as far away as the swimmer is.
      const d = camera.position.distanceTo(this.actors[0].com);
      hit.copy(ray.ray.origin).addScaledVector(ray.ray.direction, d + 4);
    } else if (!ray.ray.intersectPlane(new THREE.Plane(new THREE.Vector3(0, 1, 0), 0), hit)) {
      return;
    }
    this.world.setGoal(0, hit.x, hit.y, hit.z);
    this.userGoal = true;
  },

  /** Point the camera's wish at whoever we're following. */
  aim() {
    const a = this.actors[this.focus];
    if (!a) return;
    if (this.mode === 'fight') {
      cam.want.set(0, 0.3, 0);
    } else if (this.actors.length > 1) {
      // Frame the pack: track the leader down the course, stay centred across it.
      let lead = -1e9;
      let trailz = 1e9;
      for (const b of this.actors) {
        if (b.exploded) continue;
        lead = Math.max(lead, b.com.z);
        trailz = Math.min(trailz, b.com.z);
      }
      cam.want.set(0, 0.6, lead * 0.6 + trailz * 0.4);
    } else {
      cam.want.set(a.com.x, this.underwater ? a.com.y : Math.max(0.35, a.com.y), a.com.z);
      // Something that leaves the ground this far needs a wider shot.
      if (!this.underwater && a.com.y > 2) cam.wantDist = Math.max(cam.wantDist, 6 + a.com.y * 2.2);
    }
  },

  frame(dt) {
    if (!this.world) return;
    if (!this.paused) {
      if (this.hold > 0) {
        this.hold -= dt;
        if (this.hold <= 0) {
          const next = follow.pending;
          follow.pending = null;
          // A better creature was born while this one was performing
          // (only if we are still looking at the nursery it was born in).
          if (next && source === 'live' && !this.exhibit && this.archive.cells && this.archive.cells.get(cellKey(next)) === next) {
            selectElite(next);
            return;
          }
          if (this.mode === 'watch') this.trial = (this.trial + 1) % (TRIALS[this.task] || 1);
          this.start({ keepCamera: true });
          cam.snap = true;
          return;
        }
      } else {
        this.acc += dt * this.speed;
        let steps = Math.floor(this.acc / DT);
        this.acc -= steps * DT;
        // A slow frame can't be made up later: drop what doesn't fit
        // rather than letting a backlog build.
        steps = Math.min(steps, 12);
        if (steps > 0) {
          for (const w of this.worlds) w.step(steps);
          for (const a of this.actors) a.sync();
          syncCrates(this.world);
          this.after();
        }
      }
    }
    this.aim();
    this.readout();
  },

  /** Mode-specific bookkeeping after stepping. */
  after() {
    const { mode, task, world } = this;
    const t = world.time - world.settle;
    if (mode === 'fight') {
      const [A, B] = this.actors;
      world.setGoal(0, B.com.x, B.com.y, B.com.z);
      world.setGoal(1, A.com.x, A.com.y, A.com.z);
      if (this.result === null) {
        const out = (a) => Math.hypot(a.com.x, a.com.z) > RING + 0.15 || a.com.y < -0.35 || a.exploded;
        const oa = out(A);
        const ob = out(B);
        if (oa || ob) this.result = oa && ob ? 'draw' : oa ? 1 : 0;
        else if (world.time > 40) this.result = 'draw';
        if (this.result !== null) this.resultAt = world.time;
      } else if (world.time - this.resultAt > 3) {
        // Rematch from the other corners.
        this.swap = !this.swap;
        this.hold = 0.05;
      }
      return;
    }
    if (mode === 'watch') {
      if (world.score().done) this.hold = 1.6;
    } else if (mode === 'roam') {
      const a = this.actors[0];
      const g = a.goal;
      const d = Math.hypot(g[0] - a.com.x, g[2] - a.com.z, this.underwater ? g[1] - a.com.y : 0);
      if (task === 'chase' || this.userGoal) {
        if (d < 0.9) {
          this.goalsHit++;
          this.userGoal = false;
          if (task === 'chase') this.nextChaseGoal();
          else this.world.setGoal(0, a.com.x, a.com.y, a.com.z + 1000);
        }
      }
      if (a.exploded) this.hold = 1.0;
      if (task === 'shove' && world.crates && !this.userGoal) {
        const c = world.crate(0);
        world.setGoal(0, c[0], c[1], c[2]);
      }
    } else if (t > SECONDS[task] + 1.5) {
      this.hold = 2.2;
    }
    // Flag follows the focus creature's goal when it has a nearby one.
    const a = this.actors[this.focus];
    const g = a.goal;
    const near = Math.hypot(g[0] - a.com.x, g[2] - a.com.z) < 200;
    flag.visible = near && (task === 'chase' || this.userGoal) && this.actors.length === 1;
    if (flag.visible) flag.position.set(g[0], this.underwater ? g[1] - 0.8 : 0, g[2]);
  },

  readout() {
    const { mode, task, world } = this;
    const a = this.actors[this.focus];
    const t = Math.max(0, world.time - world.settle);
    const sp = Math.hypot(a.vel[0], a.vel[2], this.underwater ? a.vel[1] : 0);
    $('r1').textContent = `${t.toFixed(1)} s`;
    if (mode === 'watch') {
      const s = world.score();
      $('r2k').textContent = HABITATS[task].metric;
      $('r2').textContent = `${s.progress.toFixed(2)} m`;
    } else if (mode === 'roam' && task === 'shove' && this.crateStart) {
      const c = world.crate(0);
      $('r2k').textContent = 'crate moved';
      $('r2').textContent = `${Math.hypot(c[0] - this.crateStart[0], c[2] - this.crateStart[2]).toFixed(2)} m`;
    } else if (mode === 'roam') {
      $('r2k').textContent = task === 'chase' || this.goalsHit ? 'flags' : 'from start';
      $('r2').textContent = task === 'chase' || this.goalsHit ? `${this.goalsHit}` : `${Math.hypot(a.com.x, a.com.z).toFixed(1)} m`;
    } else if (mode === 'fight') {
      const r = this.result;
      $('r2k').textContent = r === null ? 'to the edge' : 'result';
      if (r === null) {
        const edge = Math.min(...this.actors.map((b) => RING - Math.hypot(b.com.x, b.com.z)));
        $('r2').textContent = `${Math.max(0, edge).toFixed(1)} m`;
      } else {
        $('r2').textContent = r === 'draw' ? 'draw' : `${this.tags[r].textContent.split(' ')[0]} wins`;
      }
      this.tags.forEach((el, i) => {
        el.classList.toggle('lead', r === i);
        el.classList.toggle('out', r !== null && r !== 'draw' && r !== i);
      });
    } else {
      $('r2k').textContent = 'leader';
      let lead = 0;
      let who = 0;
      this.actors.forEach((b, i) => {
        if (!b.exploded && b.com.z > lead) {
          lead = b.com.z;
          who = i;
        }
      });
      $('r2').textContent = `${lead.toFixed(1)} m`;
      this.tags.forEach((el, i) => el.classList.toggle('lead', i === who));
    }
    $('r3').textContent = `${sp.toFixed(2)} m/s`;
    // Lane tags.
    if (this.tags.length) {
      const w = canvas.clientWidth;
      const h = canvas.clientHeight;
      this.actors.forEach((b, i) => {
        const el = this.tags[i];
        if (!el) return;
        _v.copy(b.com);
        _v.y += b.size * 1.1 + 0.35;
        _v.project(camera);
        const vis = _v.z < 1 && Math.abs(_v.x) < 1.1 && Math.abs(_v.y) < 1.1;
        el.style.display = vis ? '' : 'none';
        if (vis) {
          el.style.left = `${((_v.x + 1) / 2) * w}px`;
          el.style.top = `${((1 - _v.y) / 2) * h}px`;
        }
      });
    }
  },
};

function pickEvenly(n, max) {
  if (n <= max) return [...Array(n).keys()];
  return [...Array(max).keys()].map((i) => Math.round((i * (n - 1)) / (max - 1)));
}

// ---------------------------------------------------------------------- UI

const zoo = { tasks: {} }; // the collection bred offline, loaded a habitat at a time
let available = []; // habitats the collection has
let family = null; // null for every family merged, or one family's index
let wasmModule = null; // compiled simulator, shared with breeding workers
let source = 'zoo'; // 'zoo' (the collection) or 'live' (bred here)
let catapult = null; // genome of the creature that cheated
const nurseries = {};
const archives = {};

function fmt(n) {
  return n >= 1e6 ? `${(n / 1e6).toFixed(1)} million` : n.toLocaleString('en-US');
}

const ROMAN = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X', 'XI', 'XII'];

async function getJson(path) {
  const r = await fetch(new URL(path, import.meta.url));
  if (!r.ok) throw new Error(`${path}: HTTP ${r.status}`);
  return r.json();
}

/**
 * The collection's archive for a task, in the shape the stage expects.
 * Evolution ran as several isolated families; `elites` is either the best
 * of all of them per cell, or one family's own map.
 */
function zooArchive(task) {
  if (!archives[task]) {
    const a = zoo.tasks[task];
    const families = a.families || [];
    let merged = a.elites;
    if (families.length) {
      // The merged map arrives as (family, cell) pointers; resolve them so
      // a creature is the same object whichever way you reach it.
      const byCell = families.map((f) => new Map(f.elites.map((e) => [e.cell.join(','), e])));
      for (const [k, f] of families.entries()) for (const e of f.elites) e.family = k;
      merged = a.elites.map((ref) => byCell[ref.family].get(ref.cell.join(',')));
    }
    archives[task] = {
      dims: a.dims,
      evals: a.evals,
      live: false,
      families,
      get elites() {
        return family !== null && families[family] ? families[family].elites : merged;
      },
      lineageOf(e) {
        return a.lineages.find((l) => l[l.length - 1].id === e.id) || [e];
      },
      /** One champion per family: eight different answers to one question. */
      racers() {
        if (families.length < 2) return null;
        return families.map((f) => f.elites.reduce((b, e) => (e.fitness > b.fitness ? e : b)));
      },
    };
  }
  return archives[task];
}

function nursery(task) {
  if (!nurseries[task]) nurseries[task] = new Nursery(stage.eng, wasmModule, task, onBirth);
  return nurseries[task];
}

function currentArchive() {
  return source === 'live' ? nursery(stage.task) : zooArchive(stage.task);
}

let showing = 0;
/**
 * Switch to a habitat (in the current source). Resolves true once it is on
 * show; false if its creatures could not be loaded or another switch
 * overtook this one.
 */
async function showTask(task) {
  // Nurseries for other habitats give their cores back.
  for (const n of Object.values(nurseries)) if (n.task !== task) n.park();
  const ticket = ++showing;
  if (source === 'zoo' && !zoo.tasks[task]) {
    // First visit to this habitat: fetch its creatures.
    $('brief').textContent = 'Fetching this habitat’s creatures…';
    try {
      const data = await getJson(`./data/${task}.json`);
      zoo.tasks[task] = data;
    } catch (err) {
      if (ticket === showing) $('brief').textContent = `Could not load this habitat (${err.message}).`;
      return false;
    }
    if (ticket !== showing) return false;
  }
  follow.pending = null;
  stage.task = task;
  stage.exhibit = null;
  stage.archive = currentArchive();
  stage.trial = 0;
  stage.ancestor = -1;
  for (const b of $('habitats').children) {
    b.setAttribute('aria-pressed', String(b.dataset.task === task));
    // Habitats the collection doesn't have yet stay clickable, so they
    // can say why, but look switched off.
    const missing = source === 'zoo' && !available.includes(b.dataset.task);
    b.setAttribute('aria-disabled', String(missing));
    b.title = missing ? 'Still being bred' : '';
  }
  for (const [id, src] of [['src-zoo', 'zoo'], ['src-live', 'live']]) $(id).setAttribute('aria-pressed', String(src === source));
  $('brief').textContent = HABITATS[task].brief;
  const [dx, dy] = stage.archive.dims;
  $('xaxis').textContent = AXIS[dx.name] || dx.name;
  $('yaxis').textContent = AXIS[dy.name] || dy.name;
  $('breed').hidden = source !== 'live';
  $('tally').hidden = source === 'live';
  $('cheat').hidden = source === 'live';
  $('about').hidden = source === 'live';
  $('maptitle').textContent = source === 'live' ? 'Bred in this browser' : 'Every body plan kept';
  if (family !== null && !(stage.archive.families && stage.archive.families[family])) family = null;
  renderFamilies();
  renderMap();
  breedStatus();
  const champ = bestOf(stage.archive);
  if (champ) selectElite(champ);
  else showNothing();
  // Keep the address pointing at this habitat, without piling up history.
  try {
    history.replaceState(null, '', `#${task}`);
  } catch {
    // Some embedders forbid it; the page works the same without.
  }
  return true;
}

/** The stage with no creature on it (a live habitat before its first birth). */
function showNothing() {
  stage.elite = null;
  stage.clear();
  buildHabitat({ kind: stage.task === 'swim' ? 'water' : 'flat' }, stage.task, { min: 0, max: 0 });
  describe();
  $('gen').hidden = true;
  $('modehint').textContent = '';
  for (const id of ['r1', 'r2', 'r3']) $(id).textContent = '–';
  cam.want.set(0, 0.5, 0);
  cam.wantDist = 7;
}

/** Chips for choosing one family's map, or all of them merged. */
function renderFamilies() {
  const fams = (source === 'zoo' && stage.archive.families) || [];
  const box = $('families');
  box.hidden = fams.length < 2;
  if (box.hidden) {
    box.replaceChildren();
    return;
  }
  // Build the chips once per archive; after that only their state changes,
  // so the one just pressed keeps keyboard focus.
  if (box.children.length !== fams.length + 1) {
    const chip = (label, value, title) => {
      const b = document.createElement('button');
      b.textContent = label;
      b.title = title;
      b.addEventListener('click', () => {
        family = value;
        follow.pending = null;
        renderFamilies();
        renderMap();
        const champ = bestOf(stage.archive);
        if (champ) selectElite(champ);
      });
      b.dataset.family = value === null ? 'all' : String(value);
      return b;
    };
    box.replaceChildren(
      chip('All', null, 'The best of every family, cell by cell'),
      ...fams.map((_, k) => chip(ROMAN[k] || `${k + 1}`, k, `Family ${ROMAN[k] || k + 1} alone`))
    );
  }
  for (const b of box.children) b.setAttribute('aria-pressed', String(b.dataset.family === (family === null ? 'all' : String(family))));
}

function bestOf(arch) {
  let b = null;
  for (const e of arch.elites) if (!b || e.fitness > b.fitness) b = e;
  return b;
}

const cellKey = (e) => e.cell.join(',');

// Who lives in each square of the map right now. Buttons look their
// occupant up when clicked, so the grid can be updated in place.
let mapCells = new Map();

function renderMap() {
  const arch = stage.archive;
  const task = stage.task;
  const H = HABITATS[task];
  const [dx, dy] = arch.dims;
  const map = $('map');
  const elites = arch.elites;
  mapCells = new Map(elites.map((e) => [cellKey(e), e]));
  const best = elites.length ? Math.max(...elites.map((e) => e.fitness)) : 0;
  const worst = elites.length ? Math.min(...elites.map((e) => e.fitness)) : 0;
  const selected = stage.elite && !stage.exhibit ? cellKey(stage.elite) : null;
  // (Re)build the buttons only when the grid's shape changes. While
  // breeding this runs twice a second; replacing buttons that often would
  // swallow clicks and keyboard focus.
  if (map.children.length !== dx.bins * dy.bins || map.dataset.cols !== String(dx.bins)) {
    map.dataset.cols = String(dx.bins);
    map.style.gridTemplateColumns = `repeat(${dx.bins}, 1fr)`;
    const cells = [];
    for (let y = dy.bins - 1; y >= 0; y--) {
      for (let x = 0; x < dx.bins; x++) {
        const b = document.createElement('button');
        b.dataset.cell = `${x},${y}`;
        b.addEventListener('click', () => {
          const e = mapCells.get(b.dataset.cell);
          if (!e) return;
          follow.pending = null;
          follow.on = false;
          selectElite(e);
        });
        cells.push(b);
      }
    }
    map.replaceChildren(...cells);
  }
  for (const b of map.children) {
    const e = mapCells.get(b.dataset.cell);
    b.classList.toggle('empty', !e);
    b.classList.toggle('champ', !!e && e.fitness === best);
    b.disabled = !e;
    if (e) {
      b.style.setProperty('--t', ((e.fitness - worst) / Math.max(1e-6, best - worst)).toFixed(3));
      const label = `${nameOf(e, task)} · ${e.fitness.toFixed(2)} ${H.unit}`;
      if (b.title !== label) {
        b.title = label;
        b.setAttribute('aria-label', label);
      }
      b.setAttribute('aria-pressed', String(b.dataset.cell === selected));
    } else {
      b.removeAttribute('title');
      b.removeAttribute('aria-pressed');
      b.setAttribute('aria-label', 'Nothing of this shape yet');
    }
  }
  $('lo').textContent = `${worst.toFixed(1)} ${H.unit}`;
  $('hi').textContent = `${best.toFixed(1)} ${H.unit}`;
  $('filled').textContent = `${elites.length} of ${dx.bins * dy.bins}`;
  $('tally').textContent = arch.evals ? `${fmt(arch.evals)} creatures tried` : '';
}

function selectElite(e) {
  // Whoever was on show before becomes the sumo opponent.
  if (stage.elite && stage.elite !== e && !stage.exhibit) stage.rival = { elite: stage.elite, task: stage.rivalTask || stage.task };
  stage.rivalTask = stage.task;
  stage.swap = false;
  stage.exhibit = null;
  stage.elite = e;
  stage.ancestor = -1;
  stage.trial = 0;
  if (stage.mode === 'line' && !stage.hasLineage()) stage.mode = 'watch';
  if (stage.mode === 'fight' && !stage.hasRival()) stage.mode = 'watch';
  const key = cellKey(e);
  for (const b of $('map').children) if (!b.disabled) b.setAttribute('aria-pressed', String(b.dataset.cell === key && mapCells.get(key) === e));
  describe();
  setMode(stage.mode);
}

function setStats(rows) {
  $('stats').replaceChildren(
    ...rows.map(([k, v]) => {
      const d = document.createElement('div');
      const dt = document.createElement('dt');
      const dd = document.createElement('dd');
      dt.textContent = k;
      dd.textContent = v;
      d.append(dt, dd);
      return d;
    })
  );
}

function describe() {
  const e = stage.elite;
  const task = stage.task;
  const H = HABITATS[task];
  const modes = ['m-watch', 'm-roam', 'm-line', 'm-race', 'm-fight'];
  if (stage.exhibit) {
    $('tagline').textContent = 'Disqualified';
    $('binomial').textContent = 'Tetrabates fraudator';
    $('common').textContent = 'the catapult: an early sprint “champion”, 17.7 m';
    setStats([['claimed', '17.72 m'], ['honest', '1.05 m'], ['generations', '17']]);
    for (const id of modes) $(id).disabled = id !== 'm-watch';
    return;
  }
  if (!e) {
    $('tagline').textContent = `${H.title}, bred here`;
    $('binomial').textContent = 'Nothing alive yet';
    $('common').textContent = 'Start breeding and the first survivors turn up within seconds.';
    setStats([['score', '–'], ['pace', '–'], ['generations', '–']]);
    for (const id of modes) $(id).disabled = true;
    return;
  }
  const best = bestOf(stage.archive);
  $('tagline').textContent = e === best ? `${H.title} champion` : `${H.title} specimen`;
  $('binomial').textContent = nameOf(e, task);
  $('common').textContent = commonOf(e, task);
  const rate = task === 'jump' ? null : e.fitness / SECONDS[task];
  setStats([
    ['score', `${e.fitness.toFixed(2)} ${H.unit}`],
    rate === null ? ['off ground', `${Math.round(e.eval.airborne * 100)}%`] : ['pace', `${rate.toFixed(2)} m/s`],
    ['generations', `${e.depth}`],
  ]);
  for (const id of modes) $(id).disabled = false;
  $('m-line').disabled = !stage.hasLineage();
  $('m-fight').disabled = !stage.hasRival();
}

const HINTS = {
  watch: 'The exact trial it was scored on, replayed step for step.',
  roam: 'Let loose with no clock. Click the ground to plant a flag and see whether it can steer.',
  line: 'Its ancestors side by side, founder to today, all starting together.',
  race: 'The best from each row of the map on one start line.',
  exhibit:
    'It paddles on the spot for seven seconds, then a bug in the physics engine’s rounded boxes fires it into the air, timed to land as the clock runs out. Evolution found the bug before I did. Boxes are square now, sudden launches are thrown out, and every winner has to do it twice.',
};
function setMode(mode) {
  if (stage.exhibit) mode = 'watch';
  stage.mode = mode;
  for (const [id, m] of [['m-watch', 'watch'], ['m-roam', 'roam'], ['m-line', 'line'], ['m-race', 'race'], ['m-fight', 'fight']]) {
    $(id).setAttribute('aria-pressed', String(m === mode));
  }
  let hint = HINTS[mode];
  if (mode === 'fight') {
    const r = stage.rivalFor();
    const who = r === stage.rival ? 'the last creature you looked at' : 'the best of the rest here';
    hint = `Against ${nameOf(r.elite, r.task)}, ${who}. Each is drawn to the other; first off the ring loses. Look at another creature, then this one, to set up a different match.`;
  }
  if (mode === 'race' && stage.archive.racers && stage.archive.racers()) {
    hint = 'Each family’s champion on one start line. The families never met, so each found its own way.';
  }
  if (mode === 'roam' && stage.task === 'shove') hint = 'Let loose with no clock and a crate to bully. Click the ground to send it somewhere else.';
  if (mode === 'roam' && stage.task === 'swim') hint = 'Let loose with no clock. Click anywhere in the water to give it somewhere to go.';
  if (mode === 'roam' && stage.task === 'chase') hint = 'Flags keep coming, with no clock. Click the ground to plant one yourself.';
  if (stage.exhibit) hint = HINTS.exhibit;
  $('modehint').textContent = hint;
  const showGen = mode === 'watch' && !stage.exhibit && stage.hasLineage();
  $('gen').hidden = !showGen;
  if (showGen) {
    const line = stage.lineage();
    const s = $('genslider');
    s.max = String(line.length - 1);
    s.value = String(stage.ancestor >= 0 ? stage.ancestor : line.length - 1);
    genLabel();
  }
  stage.start();
}
function genLabel() {
  if (!stage.elite) return;
  const line = stage.lineage();
  const a = line[Math.min(line.length - 1, Number($('genslider').value))];
  $('gennow').textContent = `generation ${a.depth} · ${a.fitness.toFixed(2)} ${HABITATS[stage.task].unit}`;
}

// ---- breeding live

// While following, the stage switches to each new champion, but only
// between trials so nothing is cut off mid-stride.
const follow = { on: true, pending: null };
let mapDirty = false;

function onBirth(elite, isBest) {
  if (source !== 'live' || stage.exhibit || stage.archive !== nurseries[stage.task]) return;
  if (stage.archive.cells.get(cellKey(elite)) !== elite) return;
  mapDirty = true;
  if (!stage.elite) selectElite(elite);
  else if (isBest && follow.on) {
    // Don't make anyone sit through a dud: cut straight to a champion
    // that's far better than what's on show, otherwise wait for the
    // current trial to finish.
    if (elite.fitness > 1.5 * stage.elite.fitness + 0.5) {
      follow.pending = null;
      selectElite(elite);
    } else follow.pending = elite;
  }
}

function breedStatus() {
  if (source !== 'live') return;
  const n = nursery(stage.task);
  $('breedgo').textContent = n.running ? 'Pause breeding' : n.evals ? 'Resume breeding' : 'Start breeding';
  $('breedgo').setAttribute('aria-pressed', String(n.running));
  const best = n.best;
  $('breedstat').textContent = n.error
    ? `Could not start background workers here (${n.error}).`
    : n.evals
    ? `${fmt(n.evals)} tried, ${n.rate.toFixed(0)} a second on ${n.workers.length} cores. Best ${best ? best.fitness.toFixed(2) : '0.00'} ${HABITATS[stage.task].unit}. ${n.flukes} flukes thrown out.`
    : 'Random boxes at first. Whatever moves gets to have offspring.';
  // Best score over time.
  const c = $('spark');
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  const w = c.clientWidth;
  const h = c.clientHeight;
  if (!w) return;
  if (c.width !== Math.round(w * dpr)) {
    c.width = Math.round(w * dpr);
    c.height = Math.round(h * dpr);
  }
  const g = c.getContext('2d');
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  g.clearRect(0, 0, w, h);
  const css = getComputedStyle(document.documentElement);
  g.strokeStyle = css.getPropertyValue('--line');
  g.lineWidth = 1;
  g.beginPath();
  g.moveTo(0, h - 0.5);
  g.lineTo(w, h - 0.5);
  g.stroke();
  if (n.history.length && best) {
    const xmax = Math.max(n.evals, 1);
    const ymax = best.fitness * 1.1;
    g.strokeStyle = css.getPropertyValue('--cell-hi');
    g.lineWidth = 1.5;
    g.beginPath();
    g.moveTo(0, h - 1);
    let last = 0;
    for (const p of n.history) {
      const x = (p.evals / xmax) * w;
      g.lineTo(x, h - 1 - (last / ymax) * (h - 4));
      g.lineTo(x, h - 1 - (p.best / ymax) * (h - 4));
      last = p.best;
    }
    g.lineTo(w, h - 1 - (last / ymax) * (h - 4));
    g.stroke();
  }
}

setInterval(() => {
  if (source !== 'live') return;
  if (mapDirty) {
    mapDirty = false;
    renderMap();
    if (stage.elite) describe();
  }
  breedStatus();
}, 500);

async function toggleBreeding() {
  const n = nursery(stage.task);
  if (n.running) n.stop();
  else {
    follow.on = true;
    try {
      await n.start();
    } catch {
      // The nursery remembers why; breedStatus shows it.
    }
  }
  breedStatus();
}

async function setSource(next) {
  if (next === source) return;
  const prev = source;
  for (const n of Object.values(nurseries)) n.park();
  source = next;
  let task = stage.task;
  if (source === 'zoo' && !available.includes(task)) task = ORDER.find((t) => available.includes(t));
  if (!(await showTask(task)) && source === next && stage.archive && stage.archive.live !== (next === 'live')) {
    // Couldn't get there (the habitat failed to load): stay where we were.
    source = prev;
  }
}

async function showCheat() {
  for (const n of Object.values(nurseries)) n.park();
  const prev = source;
  source = 'zoo';
  family = null;
  if (!(await showTask('sprint'))) {
    if (!stage.archive || stage.archive.live) source = prev;
    return;
  }
  stage.exhibit = catapult;
  for (const b of $('map').children) if (!b.disabled) b.setAttribute('aria-pressed', 'false');
  describe();
  setMode('watch');
}

function wireUI() {
  for (const task of ORDER) {
    const b = document.createElement('button');
    b.textContent = HABITATS[task].title;
    b.dataset.task = task;
    b.setAttribute('aria-pressed', 'false');
    b.addEventListener('click', () => {
      if (source === 'zoo' && !available.includes(task)) {
        $('brief').textContent = `The ${HABITATS[task].title} habitat is still being bred, so the collection has nothing to show for it yet. “Breed your own” can start it from scratch right here.`;
        return;
      }
      showTask(task);
    });
    $('habitats').append(b);
  }
  $('src-zoo').addEventListener('click', () => setSource('zoo'));
  $('src-live').addEventListener('click', () => setSource('live'));
  $('breedgo').addEventListener('click', toggleBreeding);
  $('cheat').addEventListener('click', showCheat);
  $('m-watch').addEventListener('click', () => setMode('watch'));
  $('m-roam').addEventListener('click', () => setMode('roam'));
  $('m-line').addEventListener('click', () => setMode('line'));
  $('m-race').addEventListener('click', () => setMode('race'));
  $('m-fight').addEventListener('click', () => setMode('fight'));
  $('genslider').addEventListener('input', () => {
    if (!stage.elite) return;
    const line = stage.lineage();
    const i = Number($('genslider').value);
    stage.ancestor = i === line.length - 1 ? -1 : i;
    genLabel();
    stage.trial = 0;
    stage.start({ keepCamera: true });
    cam.snap = true;
  });
  $('pause').addEventListener('click', () => {
    stage.paused = !stage.paused;
    $('pause').setAttribute('aria-pressed', String(stage.paused));
    $('pause').textContent = stage.paused ? 'Play' : 'Pause';
  });
  $('restart').addEventListener('click', () => stage.start({ keepCamera: true }));
  for (const b of document.querySelectorAll('.spd')) {
    b.addEventListener('click', () => {
      stage.speed = Number(b.dataset.s);
      for (const o of document.querySelectorAll('.spd')) o.setAttribute('aria-pressed', String(o === b));
    });
  }
}

function resize() {
  const w = canvas.clientWidth;
  const h = canvas.clientHeight;
  if (!w || !h) return;
  const dpr = Math.min(window.devicePixelRatio || 1, 2);
  // Same rounding three.js uses, or this would fire every frame at
  // fractional pixel ratios.
  if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
    renderer.setPixelRatio(dpr);
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    // On wide screens the drawer covers the left edge and the label the
    // bottom right: slide the picture so the subject sits in the clear.
    if (!stackedQuery.matches) camera.setViewOffset(w, h, -Math.min(170, w * 0.13), 50, w, h);
    else camera.clearViewOffset();
    camera.updateProjectionMatrix();
  }
}

let last = performance.now();
function tick(now) {
  const dt = Math.min(0.1, (now - last) / 1000);
  last = now;
  resize();
  stage.frame(dt);
  updateCamera(dt);
  renderer.render(scene, camera);
  requestAnimationFrame(tick);
}

async function boot() {
  readTheme();
  try {
    const wasmUrl = new URL('./mg.wasm', import.meta.url).href;
    let index;
    [wasmModule, index, catapult] = await Promise.all([compileEngine(wasmUrl), getJson('./data/index.json'), getJson('./data/catapult.json')]);
    available = index.tasks;
    stage.eng = await loadEngine(wasmModule);
  } catch (err) {
    $('loading').textContent = `Could not load the simulator or the creature data (${err.message}). If you opened this file directly, serve the folder over HTTP instead.`;
    return;
  }
  wireUI();
  const wanted = location.hash.slice(1);
  if (!(await showTask(available.includes(wanted) ? wanted : ORDER.find((t) => available.includes(t))))) {
    $('loading').textContent = 'Could not load the creatures for the first habitat. Reload to try again.';
    return;
  }
  $('loading').hidden = true;
  const retheme = () => {
    readTheme();
    if (stage.world) stage.start({ keepCamera: true });
    else if (!stage.elite) showNothing();
  };
  matchMedia('(prefers-color-scheme: dark)').addEventListener('change', retheme);
  new MutationObserver(retheme).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
  // Debug/automation hook.
  window.menagerie = {
    stage, cam, zoo, showTask, selectElite, setMode, setSource, showCheat, toggleBreeding, nursery,
    selectTask: showTask,
    // Step the simulation by hand (for filmstrips and tests).
    advance(steps) {
      for (const w of stage.worlds) w.step(steps);
      for (const a of stage.actors) a.sync();
      stage.after();
      stage.aim();
      cam.snap = true;
      updateCamera(0);
      renderer.render(scene, camera);
    },
  };
  requestAnimationFrame(tick);
}
boot();
