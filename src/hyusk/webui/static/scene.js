// 3D particle sphere — reacts to agent activity states.
// States: idle, listening, thinking, speaking, error.

import * as THREE from "three";

const sphere = document.getElementById("scene");
const statusDot = document.getElementById("status-dot");
const statusText = document.getElementById("status-text");
const statusContainer = document.getElementById("status");

const PARTICLE_COUNT = 1200;
const SPHERE_RADIUS = 1.8;

const scene3d = new THREE.Scene();
scene3d.background = null;

const camera = new THREE.PerspectiveCamera(45, 1, 0.1, 100);
camera.position.set(0, 0, 7.5);
camera.lookAt(0, 0, 0);

const renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
renderer.setPixelRatio(window.devicePixelRatio || 1);
renderer.setSize(window.innerWidth, window.innerHeight);
sphere.appendChild(renderer.domElement);

const group = new THREE.Group();
scene3d.add(group);

// Particle positions on a sphere surface (Fibonacci lattice for
// even distribution).
const positions = new Float32Array(PARTICLE_COUNT * 3);
const seeds = new Float32Array(PARTICLE_COUNT); // per-particle random phase
for (let i = 0; i < PARTICLE_COUNT; i++) {
  const phi = Math.acos(1 - 2 * (i + 0.5) / PARTICLE_COUNT);
  const theta = Math.PI * (1 + Math.sqrt(5)) * i;
  const x = Math.sin(phi) * Math.cos(theta);
  const y = Math.sin(phi) * Math.sin(theta);
  const z = Math.cos(phi);
  positions[i * 3 + 0] = x * SPHERE_RADIUS;
  positions[i * 3 + 1] = y * SPHERE_RADIUS;
  positions[i * 3 + 2] = z * SPHERE_RADIUS;
  seeds[i] = Math.random();
}

const geometry = new THREE.BufferGeometry();
geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));

const material = new THREE.PointsMaterial({
  color: 0x4ad6ff,
  size: 0.045,
  transparent: true,
  opacity: 0.9,
  sizeAttenuation: true,
  depthWrite: false,
});

const points = new THREE.Points(geometry, material);
group.add(points);

// Soft glow halo (a slightly larger transparent sphere shell).
const haloGeo = new THREE.SphereGeometry(SPHERE_RADIUS * 1.05, 32, 32);
const haloMat = new THREE.MeshBasicMaterial({
  color: 0x4ad6ff,
  transparent: true,
  opacity: 0.04,
  side: THREE.BackSide,
});
const halo = new THREE.Mesh(haloGeo, haloMat);
group.add(halo);

// State machine.
let state = "idle"; // idle | listening | thinking | speaking | error
let stateChangedAt = performance.now();
let activityAmp = 0.0; // 0..1, driven by state
let pulsePhase = 0; // for "speaking" animation

const STATE_INFO = {
  idle:      { color: 0x4ad6ff, amp: 0.04, label: "idle" },
  listening: { color: 0x6cf09a, amp: 0.18, label: "listening" },
  thinking:  { color: 0xb58dff, amp: 0.22, label: "thinking" },
  speaking:  { color: 0xff7e6b, amp: 0.32, label: "speaking" },
  error:     { color: 0xff6b81, amp: 0.28, label: "error" },
};

function setState(next) {
  if (next === state) return;
  state = next;
  stateChangedAt = performance.now();
  const info = STATE_INFO[state] || STATE_INFO.idle;
  // Update particle + halo colors
  const color = new THREE.Color(info.color);
  material.color.copy(color);
  haloMat.color.copy(color);
  // Update HUD
  if (statusDot && statusContainer) {
    statusContainer.className = "status " + (
      state === "idle" ? "connected" :
      state === "error" ? "error" : state
    );
  }
  if (statusText) {
    statusText.textContent = info.label;
  }
  activityAmp = info.amp;
}

window.__hyuskScene = window.__hyuskScene || {};
window.__hyuskScene.setState = setState;

function onResize() {
  const w = window.innerWidth, h = window.innerHeight;
  renderer.setSize(w, h);
  camera.aspect = w / h;
  camera.updateProjectionMatrix();
}
window.addEventListener("resize", onResize);

const clock = new THREE.Clock();
function tick() {
  const t = clock.getElapsedTime();
  const dt = clock.getDelta();

  // Whole sphere rotates slowly.
  group.rotation.y += dt * 0.06;
  group.rotation.x = Math.sin(t * 0.3) * 0.08;

  // Pulse the particle ring outward when "speaking".
  const since = (performance.now() - stateChangedAt) / 1000;
  let amp = activityAmp;
  if (state === "speaking") {
    pulsePhase += dt * 4.0;
    amp += Math.sin(pulsePhase) * 0.06;
  } else if (state === "thinking") {
    amp += Math.sin(t * 1.2) * 0.04;
  } else if (state === "listening") {
    amp += Math.sin(t * 2.0 + 0.5) * 0.05;
  }

  // Apply per-particle offset along its radial direction.
  const arr = geometry.attributes.position.array;
  for (let i = 0; i < PARTICLE_COUNT; i++) {
    const ox = arr[i * 3 + 0], oy = arr[i * 3 + 1], oz = arr[i * 3 + 2];
    const len = Math.sqrt(ox * ox + oy * oy + oz * oz) || 1;
    const seed = seeds[i];
    const wobble = 1 + amp * (1 + 0.4 * Math.sin(t * 2.0 + seed * 6.28));
    arr[i * 3 + 0] = (ox / len) * SPHERE_RADIUS * wobble;
    arr[i * 3 + 1] = (oy / len) * SPHERE_RADIUS * wobble;
    arr[i * 3 + 2] = (oz / len) * SPHERE_RADIUS * wobble;
  }
  geometry.attributes.position.needsUpdate = true;

  // Soft halo breathes.
  haloMat.opacity = 0.04 + 0.04 * Math.sin(t * 1.5) + amp * 0.2;

  renderer.render(scene3d, camera);
  requestAnimationFrame(tick);
}
onResize();
tick();
