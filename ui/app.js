"use strict";
/* NetWatch 2 UI */

// ============================================================ bridge
const bridgeReady = window.NW_BROWSER ? Promise.resolve() : new Promise(res => {
  if (window.pywebview && window.pywebview.api && window.pywebview.api.get_state) return res();
  window.addEventListener("pywebviewready", () => res());
});
async function call(name, args) {
  await bridgeReady;
  if (window.NW_BROWSER) {
    const r = await fetch("/api/" + name, {
      method: "POST", headers: { "Content-Type": "application/json", "X-NW-Token": window.NW_TOKEN || "" },
      body: JSON.stringify(args)
    });
    if (r.status === 401 && window.NW_LAN) { try { sessionStorage.removeItem("nwtok"); } catch (e) {} location.reload(); }
    return r.json();
  }
  return window.pywebview.api[name](...args);
}
const API = new Proxy({}, { get: (_, name) => (...args) => call(name, args) });

// ============================================================ helpers
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const isNum = v => typeof v === "number" && isFinite(v);
const fmtMs = (v, dp = 0) => isNum(v) ? (v < 1 && dp === 0 ? "<1" : v.toFixed(dp)) : "—";
const mbps = bps => isNum(bps) ? bps * 8 / 1e6 : null;
function fmtMbps(v) { if (!isNum(v)) return "—"; return v >= 100 ? v.toFixed(0) : v >= 10 ? v.toFixed(1) : v.toFixed(2); }
function fmtRate(bps) {
  if (!isNum(bps)) return ["—", ""];
  let b = bps * 8; const u = ["bps", "Kbps", "Mbps", "Gbps"]; let i = 0;
  while (b >= 999.5 && i < 3) { b /= 1000; i++; }
  return [i === 0 ? b.toFixed(0) : b >= 100 ? b.toFixed(0) : b.toFixed(1), u[i]];
}
function fmtBytes(n) {
  if (!isNum(n)) return "—"; const u = ["B", "KB", "MB", "GB", "TB"]; let i = 0;
  while (n >= 1024 && i < 4) { n /= 1024; i++; }
  return (i === 0 ? n.toFixed(0) : n.toFixed(1)) + " " + u[i];
}
function fmtDur(s) {
  s = Math.max(0, Math.round(s || 0)); const d = Math.floor(s / 86400), h = Math.floor(s % 86400 / 3600), m = Math.floor(s % 3600 / 60);
  if (d) return `${d}d ${h}h`; if (h) return `${h}h ${m}m`; if (m) return `${m}m ${s % 60}s`; return `${s}s`;
}
function fmtAgo(ts) {
  if (!ts) return "never"; const s = Date.now() / 1000 - ts;
  if (s < 45) return "just now"; if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`; return `${Math.round(s / 86400)} d ago`;
}
const fmtClock = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
const fmtClockS = ts => new Date(ts * 1000).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtDateTime = ts => new Date(ts * 1000).toLocaleString([], { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const fmtDay = ts => new Date(ts * 1000).toLocaleDateString([], { weekday: "short", day: "numeric", month: "short" });
const plural = (n, w) => `${n} ${w}${n === 1 ? "" : "s"}`;
function toast(msg, kind = "") {
  const t = document.createElement("div"); t.className = `toast ${kind}`; t.textContent = msg;
  $("#toasts").appendChild(t); setTimeout(() => t.remove(), 4200);
}
function avatarColor(s) {
  let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) % 360; return `hsl(${h} 65% 48%)`;
}

// ============================================================ icons
const ICONS = {
  logo: '<path d="M5 13a10 10 0 0 1 14 0"/><path d="M8.5 16.5a5 5 0 0 1 7 0"/><path d="M2 9.5a15 15 0 0 1 20 0"/><circle cx="12" cy="20" r="1.2" fill="currentColor"/>',
  dashboard: '<rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/>',
  devices: '<rect x="2" y="4" width="14" height="10" rx="1.5"/><path d="M6 18h6M9 14v4"/><rect x="17" y="8" width="5" height="12" rx="1"/>',
  apps: '<rect x="3" y="3" width="7" height="7" rx="2"/><rect x="14" y="3" width="7" height="7" rx="2"/><rect x="3" y="14" width="7" height="7" rx="2"/><rect x="14" y="14" width="7" height="7" rx="2"/>',
  wifi: '<path d="M5 12.55a11 11 0 0 1 14 0"/><path d="M1.42 9a16 16 0 0 1 21.16 0"/><path d="M8.53 16.11a6 6 0 0 1 6.95 0"/><circle cx="12" cy="20" r="1" fill="currentColor"/>',
  speed: '<path d="M12 14l4-4"/><path d="M3.34 19a10 10 0 1 1 17.32 0"/>',
  services: '<path d="M22 12h-4l-3 9L9 3l-3 9H2"/>',
  dns: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/>',
  route: '<circle cx="6" cy="19" r="3"/><path d="M9 19h8.5a3.5 3.5 0 0 0 0-7h-11a3.5 3.5 0 0 1 0-7H15"/><circle cx="18" cy="5" r="3"/>',
  history: '<path d="M3 3v5h5"/><path d="M3.05 13A9 9 0 1 0 6 5.3L3 8"/><path d="M12 7v5l4 2"/>',
  events: '<path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/>',
  settings: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 1 1-4 0v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 1 1 0-4h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 1 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 1 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/>',
  check: '<path d="M20 6L9 17l-5-5"/>',
  x: '<path d="M18 6L6 18M6 6l12 12"/>',
  alert: '<path d="M10.29 3.86L1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><path d="M12 9v4M12 17h.01"/>',
  info: '<circle cx="12" cy="12" r="10"/><path d="M12 16v-4M12 8h.01"/>',
  bolt: '<path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/>',
  down: '<path d="M12 5v14M19 12l-7 7-7-7"/>',
  up: '<path d="M12 19V5M5 12l7-7 7 7"/>',
  clock: '<circle cx="12" cy="12" r="10"/><path d="M12 6v6l4 2"/>',
  refresh: '<path d="M23 4v6h-6M1 20v-6h6"/><path d="M3.51 9a9 9 0 0 1 14.85-3.36L23 10M1 14l4.64 4.36A9 9 0 0 0 20.49 15"/>',
  search: '<circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/>',
  play: '<polygon points="6 3 20 12 6 21 6 3"/>',
  stop: '<rect x="5" y="5" width="14" height="14" rx="2"/>',
  plus: '<path d="M12 5v14M5 12h14"/>',
  trash: '<path d="M3 6h18M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6M9 6V4a1 1 0 0 1 1-1h4a1 1 0 0 1 1 1v2"/>',
  edit: '<path d="M12 20h9"/><path d="M16.5 3.5a2.12 2.12 0 0 1 3 3L7 19l-4 1 1-4z"/>',
  power: '<path d="M18.36 6.64a9 9 0 1 1-12.73 0M12 2v10"/>',
  shield: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/>',
  grid: '<rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/>',
  list: '<path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/>',
  map: '<circle cx="12" cy="12" r="2.5"/><circle cx="4" cy="6" r="2"/><circle cx="20" cy="6" r="2"/><circle cx="4" cy="19" r="2"/><circle cx="20" cy="19" r="2"/><path d="M6 7l4 3.5M18 7l-4 3.5M6 18l4-4M18 18l-4-4"/>',
  globe: '<circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15 15 0 0 1 0 20 15 15 0 0 1 0-20"/>',
  cloud: '<path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/>',
  download: '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4M7 10l5 5 5-5M12 15V3"/>',
  file: '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/>',
  pause: '<rect x="6" y="4" width="4" height="16" rx="1"/><rect x="14" y="4" width="4" height="16" rx="1"/>',
  folder: '<path d="M22 19a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h5l2 3h9a2 2 0 0 1 2 2z"/>',
  external: '<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6M15 3h6v6M10 14L21 3"/>',
  wrench: '<path d="M14.7 6.3a1 1 0 0 0 0 1.4l1.6 1.6a1 1 0 0 0 1.4 0l3.77-3.77a6 6 0 0 1-7.94 7.94l-6.91 6.91a2.12 2.12 0 0 1-3-3l6.91-6.91a6 6 0 0 1 7.94-7.94l-3.76 3.76z"/>',
  chat: '<path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/><path d="M8 9h8M8 13h5"/>',
  usage: '<path d="M21.21 15.89A10 10 0 1 1 8 2.83"/><path d="M22 12A10 10 0 0 0 12 2v10z"/>',
  sites: '<path d="M3 21h18M5 21V7l7-4 7 4v14"/><path d="M9 21v-6h6v6M9 10h.01M15 10h.01"/>',
  doctor: '<path d="M4.8 2.3A.3.3 0 1 0 5 2H4a2 2 0 0 0-2 2v5a6 6 0 0 0 6 6 6 6 0 0 0 6-6V4a2 2 0 0 0-2-2h-1a.2.2 0 1 0 .3.3"/><path d="M8 15v1a6 6 0 0 0 6 6 6 6 0 0 0 6-6v-4"/><circle cx="20" cy="10" r="2"/>',
  lock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/>',
  unlock: '<rect x="3" y="11" width="18" height="11" rx="2"/><path d="M7 11V7a5 5 0 0 1 9.9-1"/>',
  eye: '<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/>',
  record: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3" fill="currentColor"/>',
  moon: '<path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>',
  timeline: '<path d="M3 6h7M14 6h7M3 12h3M10 12h11M3 18h11M18 18h3"/>',
  phone2: '<rect x="5" y="2" width="14" height="20" rx="2"/><path d="M12 18h.01"/>',
  sparkle: '<path d="M12 3l1.9 5.8L20 11l-6.1 2.2L12 19l-1.9-5.8L4 11l6.1-2.2z"/>',
  vpn: '<path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="M9 12l2 2 4-4"/>',
  // device types
  router: '<rect x="2" y="13" width="20" height="8" rx="2"/><path d="M6 17h.01M10 17h.01M7 13l-2-7M17 13l2-7"/><path d="M15 9a4 4 0 0 0-6 0"/>',
  phone: '<rect x="6" y="2" width="12" height="20" rx="2.5"/><path d="M11 18h2"/>',
  tablet: '<rect x="4" y="2" width="16" height="20" rx="2"/><path d="M11 18h2"/>',
  pc: '<rect x="2" y="3" width="20" height="13" rx="2"/><path d="M8 21h8M12 16v5"/>',
  tv: '<rect x="2" y="5" width="20" height="13" rx="2"/><path d="M8 22h8M7 2l5 3 5-3"/>',
  printer: '<path d="M6 9V2h12v7"/><rect x="2" y="9" width="20" height="9" rx="2"/><rect x="6" y="14" width="12" height="8"/>',
  speaker: '<rect x="5" y="2" width="14" height="20" rx="2"/><circle cx="12" cy="14" r="4"/><path d="M12 6h.01"/>',
  console: '<path d="M6 11h4M8 9v4M15 12h.01M18 10h.01"/><path d="M17.32 5H6.68a4 4 0 0 0-3.98 3.59L2 15a3 3 0 0 0 5.4 1.8L9 15h6l1.6 1.8A3 3 0 0 0 22 15l-.7-6.41A4 4 0 0 0 17.32 5z"/>',
  camera: '<path d="M23 7l-7 5 7 5V7z"/><rect x="1" y="5" width="15" height="14" rx="2"/>',
  nas: '<rect x="3" y="2" width="18" height="8" rx="2"/><rect x="3" y="14" width="18" height="8" rx="2"/><path d="M7 6h.01M7 18h.01"/>',
  iot: '<path d="M9 18h6M10 22h4"/><path d="M12 2a7 7 0 0 0-4 12.74V17h8v-2.26A7 7 0 0 0 12 2z"/>',
  network: '<rect x="9" y="2" width="6" height="6" rx="1"/><rect x="2" y="16" width="6" height="6" rx="1"/><rect x="16" y="16" width="6" height="6" rx="1"/><path d="M5 16v-3h14v3M12 12V8"/>',
  device: '<circle cx="12" cy="12" r="9"/><path d="M12 8v4l2 2"/>',
};
const icon = (n, cls = "") => `<svg class="${cls}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[n] || ICONS.device}</svg>`;
const DEVICE_TYPES = ["router", "pc", "phone", "tablet", "tv", "speaker", "console", "printer", "camera", "nas", "iot", "network", "device"];
const TYPE_LABEL = { router: "Router", pc: "Computer", phone: "Phone", tablet: "Tablet", tv: "TV / streamer", speaker: "Smart speaker", console: "Games console", printer: "Printer", camera: "Camera", nas: "NAS / storage", iot: "Smart home", network: "Network gear", device: "Other device" };

// ============================================================ charts
const COL = { cyan: "#38bdf8", indigo: "#818cf8", good: "#22c55e", warn: "#f59e0b", bad: "#f43f5e", teal: "#2dd4bf", pink: "#f472b6", amber: "#fbbf24", violet: "#a78bfa" };
const SERIES = [COL.cyan, COL.indigo, COL.teal, COL.pink, COL.amber, COL.violet, COL.good];
const cssv = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
function applyChartTheme() {
  Chart.defaults.color = cssv("--muted");
  Chart.defaults.borderColor = cssv("--grid-line");
  Chart.defaults.font.family = cssv("--font");
  Chart.defaults.font.size = 11;
  Chart.defaults.animation.duration = 350;
  Chart.defaults.plugins.legend.display = false;
  Chart.defaults.plugins.tooltip.backgroundColor = cssv("--surface-solid");
  Chart.defaults.plugins.tooltip.titleColor = cssv("--text");
  Chart.defaults.plugins.tooltip.bodyColor = cssv("--text-2");
  Chart.defaults.plugins.tooltip.borderColor = cssv("--border-strong");
  Chart.defaults.plugins.tooltip.borderWidth = 1;
  Chart.defaults.plugins.tooltip.padding = 10;
  Chart.defaults.plugins.tooltip.cornerRadius = 10;
  Chart.defaults.plugins.tooltip.usePointStyle = true;
}
function fillGrad(color, alpha = 0.35) {
  return ctx => {
    const { chart } = ctx; const { ctx: c, chartArea } = chart;
    if (!chartArea) return color + "22";
    const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, color + Math.round(alpha * 255).toString(16).padStart(2, "0"));
    g.addColorStop(1, color + "00");
    return g;
  };
}
let charts = [];
function mkChart(canvas, cfg) { const c = new Chart(canvas, cfg); charts.push(c); return c; }
function timeLine(canvas, { datasets, yFmt = v => v, yMin = 0, yMax, span, dateFmt, y2, tickFmt, y2max }) {
  const scales = {
    x: { type: "linear", grid: { display: false }, ticks: { maxTicksLimit: 7, callback: v => (dateFmt || tickFmt || fmtClock)(v) },
         ...(span ? { min: undefined } : {}) },
    y: { min: yMin, max: yMax, grid: { color: cssv("--grid-line") }, border: { display: false },
         ticks: { maxTicksLimit: 5, callback: v => yFmt(v) } },
  };
  if (y2) scales.y2 = { position: "right", min: 0, suggestedMax: y2max, grid: { display: false }, border: { display: false }, ticks: { maxTicksLimit: 5, callback: y2 } };
  const bounds = { id: "xbounds", beforeUpdate(ch) {
    let lo = Infinity, hi = -Infinity;
    ch.data.datasets.forEach(d => (d.data || []).forEach(p => { if (p && isNum(p.x)) { lo = Math.min(lo, p.x); hi = Math.max(hi, p.x); } }));
    if (isFinite(lo) && hi > lo) { ch.options.scales.x.min = lo; ch.options.scales.x.max = hi; }
  } };
  return mkChart(canvas, {
    type: "line", plugins: [bounds],
    data: { datasets: datasets.map((d, i) => ({
      borderColor: d.color || SERIES[i % SERIES.length], backgroundColor: d.fill === false ? "transparent" : fillGrad(d.color || SERIES[i % SERIES.length], d.alpha ?? 0.28),
      fill: d.fill !== false, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0.35, spanGaps: d.spanGaps ?? false,
      parsing: false, ...d })) },
    options: {
      responsive: true, maintainAspectRatio: false, interaction: { mode: "index", intersect: false },
      scales,
      plugins: { tooltip: { callbacks: { title: items => items.length ? (dateFmt ? fmtDateTime(items[0].parsed.x) : new Date(items[0].parsed.x * 1000).toLocaleTimeString()) : "",
        label: it => ` ${it.dataset.label}: ${it.parsed.y == null ? "—" : (it.dataset.fmt || yFmt)(it.parsed.y)}` } } },
    },
  });
}

// ============================================================ widgets
function ring(pct, color, iconName, size = 58, stroke = 6) {
  const r = (size - stroke) / 2, c = 2 * Math.PI * r, p = Math.max(0, Math.min(1, pct || 0));
  return `<div class="ring" style="width:${size}px;height:${size}px"><svg viewBox="0 0 ${size} ${size}">
    <circle class="track" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke-width="${stroke}"/>
    <circle class="bar" cx="${size / 2}" cy="${size / 2}" r="${r}" fill="none" stroke="${color}" stroke-width="${stroke}"
      stroke-dasharray="${c}" stroke-dashoffset="${c * (1 - p)}"/></svg>
    <div class="icon">${iconName ? icon(iconName) : ""}</div></div>`;
}
function kpi({ label, value, unit = "", foot = "", pct = 0, color = COL.cyan, ic }) {
  return `<div class="card kpi">${ring(pct, color, ic)}<div class="grow"><div class="kpi-label">${label}</div>
    <div class="kpi-value">${value}<small>${unit}</small></div><div class="kpi-foot">${foot}</div></div></div>`;
}
function sparkSvg(points, color = COL.cyan, w = 120, h = 32) {
  const vals = points.map(p => p[1]).filter(isNum);
  if (vals.length < 2) return `<svg width="${w}" height="${h}"></svg>`;
  const max = Math.max(...vals) * 1.15 || 1, n = points.length;
  let d = "", pen = false;
  points.forEach((p, i) => {
    const x = (i / (n - 1)) * w;
    if (!isNum(p[1])) { pen = false; return; }
    const y = h - (p[1] / max) * (h - 4) - 2;
    d += (pen ? "L" : "M") + x.toFixed(1) + " " + y.toFixed(1); pen = true;
  });
  return `<svg width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><path d="${d}" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>`;
}
function signalBars(pct) {
  const n = pct >= 80 ? 4 : pct >= 60 ? 3 : pct >= 40 ? 2 : pct > 0 ? 1 : 0;
  return `<span class="signal-bars">${[5, 8, 11, 14].map((h, i) => `<i class="${i < n ? "on" : ""}" style="height:${h}px;${i < n && pct < 40 ? "background:var(--warn)" : ""}"></i>`).join("")}</span>`;
}
const levelColor = l => ({ good: COL.good, warn: COL.warn, bad: COL.bad }[l] || "#94a3b8");
const latColor = (v, thr) => !isNum(v) ? "#94a3b8" : v > thr ? COL.bad : v > thr * 0.6 ? COL.warn : COL.good;

function openDrawer(html) { $("#drawer").innerHTML = html; $("#drawer").classList.add("on"); $("#scrim").classList.add("on"); }
function openModal(html) { $("#modal").innerHTML = html; $("#modal").classList.add("on"); $("#scrim").classList.add("on"); }
function closeOverlays() { $("#drawer").classList.remove("on"); $("#modal").classList.remove("on"); $("#scrim").classList.remove("on"); }
$("#scrim").addEventListener("click", closeOverlays);
document.addEventListener("keydown", e => { if (e.key === "Escape") closeOverlays(); });

// ============================================================ app shell / router
const NAV = [
  ["Monitor", [["dashboard", "Dashboard"], ["devices", "Devices"], ["apps", "Apps & traffic"], ["wifi", "Wi-Fi"], ["usage", "Data usage"]]],
  ["Protect", [["security", "Security"]]],
  ["Diagnose", [["doctor", "Troubleshooter"], ["speed", "Speed test"], ["services", "Services"], ["dns", "DNS"], ["trace", "Traceroute"], ["tools", "More tests"]]],
  ["Insight", [["history", "History & reports"], ["events", "Events"], ["ask", "Ask NetWatch"], ["sites", "Sites"]]],
  ["", [["settings", "Settings"]]],
];
const NAV_ICON = { dashboard: "dashboard", devices: "devices", apps: "apps", wifi: "wifi", usage: "usage", security: "shield", doctor: "doctor", speed: "speed", services: "services", dns: "dns", trace: "route", tools: "wrench", history: "history", events: "events", ask: "chat", sites: "sites", settings: "settings" };
let STATE = null, current = null, pageTimer = null, pageObj = null;

function renderNav() {
  $("#brandLogo").innerHTML = icon("logo");
  $("#nav").innerHTML = NAV.map(([sec, items]) => (sec ? `<div class="nav-section">${sec}</div>` : `<div style="height:10px"></div>`) + items.map(([id, label]) =>
    `<div class="nav-item ${current === id ? "active" : ""}" data-go="${id}">${icon(NAV_ICON[id])}<span>${label}</span><span class="nav-badge" id="badge-${id}" style="display:none"></span></div>`).join("")).join("");
  $$("#nav .nav-item").forEach(el => el.onclick = () => go(el.dataset.go));
  updateBadges();
}
function updateBadges() {
  if (!STATE) return;
  const b = (id, n, ok) => { const el = $("#badge-" + id); if (!el) return; el.style.display = n ? "" : "none"; el.textContent = n; el.className = "nav-badge" + (ok ? " ok" : ""); };
  b("devices", STATE.devices.new, true);
  b("services", STATE.services.down);
  const ex = STATE.extra || {};
  b("security", (ex.spoof ? 1 : 0) + (ex.captive && ex.captive.portal ? 1 : 0));
}
function go(id) {
  if (!PAGES[id]) id = "dashboard";
  if (pageObj && pageObj.destroy) pageObj.destroy();
  charts.forEach(c => c.destroy()); charts = [];
  clearInterval(pageTimer); pageTimer = null;
  current = id; location.hash = id;
  $$("#nav .nav-item").forEach(el => el.classList.toggle("active", el.dataset.go === id));
  closeOverlays();
  const main = $("#main"); main.scrollTop = 0;
  pageObj = PAGES[id];
  main.innerHTML = `<div class="fade-in">${pageObj.shell()}</div>`;
  pageObj.init && pageObj.init();
  if (pageObj.refresh) {
    pageObj.refresh();
    if (pageObj.interval) pageTimer = setInterval(() => pageObj.refresh(), pageObj.interval);
  }
  if (STATE && pageObj.onState) pageObj.onState(STATE);
}
const head = (title, sub, actions = "") => `<div class="page-head"><div><h1 class="page-title">${title}</h1><div class="page-sub">${sub}</div></div><div class="actions">${actions}</div></div>`;

async function pollState() {
  try {
    const s = await API.get_state();
    if (s && !s.error) {
      const theme = s.theme === "light" ? "light" : "dark";
      STATE = s;
      if (document.documentElement.dataset.theme !== theme && !window.NW_THEME_PREVIEW) { document.documentElement.dataset.theme = theme; applyChartTheme(); if (current) go(current); }
      renderSidebarStatus(s); updateBadges();
      if (pageObj && pageObj.onState) pageObj.onState(s);
    }
  } catch (e) { console.error(e); }
  setTimeout(pollState, 1000);
}
function renderSidebarStatus(s) {
  const st = s.status;
  const paused = s.alerts_paused ? `<div class="row small muted" style="margin-top:6px">${icon("pause", "")}Alerts paused until ${fmtClock(s.paused_until)}</div>` : "";
  $("#sidebarStatus").innerHTML = `<span class="dot ${st.level} live"></span><div class="grow"><div class="t">${esc(st.title)}</div>
    <div class="s">${isNum(s.latency) ? fmtMs(s.latency) + " ms · " : ""}${fmtRate(s.down)[0]} ${fmtRate(s.down)[1]} ↓</div>${paused}</div>
    <button class="btn ghost sm" id="pauseBtn" title="Pause alerts" style="padding:5px">${icon(s.alerts_paused ? "play" : "pause")}</button>`;
  $("#pauseBtn").onclick = () => s.alerts_paused ? API.pause_alerts(0).then(() => toast("Alerts resumed", "good")) : openPause();
  $$("svg", $("#sidebarStatus .row") || document.createElement("div")).forEach(x => { x.style.width = "13px"; x.style.height = "13px"; });
}
function openPause() {
  openModal(`<h3 style="margin-top:0">Pause alerts</h3><p class="muted">NetWatch keeps monitoring and logging, but won't pop up or send remote alerts.</p>
    <div class="row wrap" style="gap:8px">${[[15, "15 minutes"], [60, "1 hour"], [240, "4 hours"], [480, "8 hours"], [1440, "24 hours"]].map(([m, l]) => `<button class="btn" data-m="${m}">${l}</button>`).join("")}</div>`);
  $$("#modal [data-m]").forEach(b => b.onclick = async () => { await API.pause_alerts(+b.dataset.m); closeOverlays(); toast(`Alerts paused for ${b.textContent}`); });
}

// ============================================================ PAGES
const PAGES = {};

// ------------------------------------------------------------ Dashboard
PAGES.dashboard = {
  shell() {
    return `<div id="hero"></div>
    <div class="grid g-6 mt" id="kpis"></div>
    <div class="grid g-3 mt">
      <div class="card span-2"><div class="card-head"><div class="card-title">${icon("clock")}Latency</div><div class="legend" id="latLegend"></div></div><div class="chart-box"><canvas id="latChart"></canvas></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("globe")}Targets</div><span class="card-sub">last 60 s</span></div><div id="targets"></div></div>
    </div>
    <div class="grid g-3 mt">
      <div class="card span-2"><div class="card-head"><div class="card-title">${icon("bolt")}Bandwidth</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Download</span><span><i style="background:${COL.indigo}"></i>Upload</span></div></div><div class="chart-box"><canvas id="bwChart"></canvas></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("devices")}Devices online</div><a class="card-sub" href="#devices">View all</a></div><div class="row" style="gap:18px"><div style="width:150px;height:150px;position:relative"><canvas id="devChart"></canvas><div id="devCenter" style="position:absolute;inset:0;display:grid;place-items:center;text-align:center;pointer-events:none"></div></div><div class="grow" id="devLegend"></div></div></div>
    </div>
    <div class="grid g-4 mt" id="qualityRow"></div>
    <div class="grid g-3 mt">
      <div class="card" id="speedCard"></div>
      <div class="card" id="healthCard"></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("events")}Recent events</div><a class="card-sub" href="#events">View all</a></div><div id="recentEvents"></div></div>
    </div>`;
  },
  init() {
    this.lat = timeLine($("#latChart"), { datasets: [], yFmt: v => v + " ms", tickFmt: fmtClockS });
    this.bw = timeLine($("#bwChart"), { datasets: [{ label: "Download", color: COL.cyan, data: [], fmt: v => fmtMbps(v) + " Mbps" }, { label: "Upload", color: COL.indigo, data: [], fmt: v => fmtMbps(v) + " Mbps" }], yFmt: v => fmtMbps(v), tickFmt: fmtClockS });
    this.dev = mkChart($("#devChart"), { type: "doughnut", data: { labels: [], datasets: [{ data: [], backgroundColor: SERIES, borderWidth: 0, spacing: 2, borderRadius: 4 }] }, options: { cutout: "74%", responsive: true, maintainAspectRatio: false } });
  },
  onState(s) {
    const thr = 150;
    const st = s.status, pub = s.public || {};
    $("#hero").innerHTML = `<div class="card hero ${st.level}"><div class="pulse"><div class="core">${icon(st.level === "bad" ? "x" : st.level === "warn" ? "alert" : "check")}</div></div>
      <div class="hero-text"><div class="hero-title">${esc(st.title)}</div><div class="hero-detail">${esc(st.detail)}</div></div>
      <div class="hero-meta"><div><div class="k">Provider</div><div class="v">${esc(pub.isp || "—")}</div></div>
      <div><div class="k">Public IP</div><div class="v">${esc(pub.ip || "—")}</div></div>
      <div><div class="k">Local IP</div><div class="v">${esc(s.net.local_ip || "—")}</div></div>
      <div><div class="k">Uptime (session)</div><div class="v">${isNum(s.uptime) ? s.uptime.toFixed(2) + "%" : "—"}</div></div></div></div>`;
    const [dv, du] = fmtRate(s.down), [uv, uu] = fmtRate(s.up);
    const plan = s.plan || {};
    const peakDown = Math.max(1, ...s.bw_series.map(p => p[1]));
    const wifi = s.wifi && s.wifi.connected ? s.wifi : null;
    $("#kpis").innerHTML = [
      kpi({ label: "Latency", value: fmtMs(s.latency), unit: "ms", foot: `Jitter ${fmtMs(s.jitter, 1)} ms`, pct: isNum(s.latency) ? Math.min(1, s.latency / 200) : 0, color: latColor(s.latency, thr), ic: "clock" }),
      kpi({ label: "Packet loss", value: isNum(s.loss) ? s.loss.toFixed(1) : "—", unit: "%", foot: "last 30 probes", pct: isNum(s.loss) ? Math.max(0.03, Math.min(1, s.loss / 10)) : 0, color: !isNum(s.loss) ? "#94a3b8" : s.loss < 1 ? COL.good : s.loss < 5 ? COL.warn : COL.bad, ic: "alert" }),
      kpi({ label: "Download", value: dv, unit: du, foot: `${fmtBytes(s.session.rx)} this session`, pct: plan.down ? mbps(s.down) / plan.down : s.down / peakDown, color: COL.cyan, ic: "down" }),
      kpi({ label: "Upload", value: uv, unit: uu, foot: `${fmtBytes(s.session.tx)} this session`, pct: plan.up ? mbps(s.up) / plan.up : s.up / Math.max(1, ...s.bw_series.map(p => p[2])), color: COL.indigo, ic: "up" }),
      wifi ? kpi({ label: "Wi-Fi signal", value: fmtMs(wifi.signal), unit: "%", foot: `${esc(wifi.ssid || "")} · ${esc(wifi.band || "")}`, pct: wifi.signal / 100, color: wifi.signal >= 60 ? COL.good : wifi.signal >= 35 ? COL.warn : COL.bad, ic: "wifi" })
           : kpi({ label: "Router", value: fmtMs(s.router), unit: "ms", foot: esc(s.net.gateway || "not detected"), pct: isNum(s.router) ? Math.min(1, s.router / 20) : 0, color: isNum(s.router) ? COL.good : COL.bad, ic: "router" }),
      kpi({ label: "DNS lookup", value: fmtMs(s.dns_ms), unit: "ms", foot: "your DNS server", pct: isNum(s.dns_ms) ? Math.min(1, s.dns_ms / 150) : 0, color: latColor(s.dns_ms, 120), ic: "dns" }),
    ].join("");

    // latency chart
    const names = Object.keys(s.lat_series);
    names.forEach((n, i) => {
      let ds = this.lat.data.datasets.find(d => d.label === n);
      if (!ds) { ds = { label: n, borderColor: n === "Router" ? COL.good : SERIES[i % SERIES.length], backgroundColor: fillGrad(n === "Router" ? COL.good : SERIES[i % SERIES.length], 0.12), fill: true, borderWidth: 2, pointRadius: 0, tension: 0.35, parsing: false, data: [] }; this.lat.data.datasets.push(ds); }
      ds.data = s.lat_series[n].map(([t, v]) => ({ x: t, y: v }));
    });
    this.lat.data.datasets = this.lat.data.datasets.filter(d => names.includes(d.label));
    this.lat.update("none");
    $("#latLegend").innerHTML = this.lat.data.datasets.map(d => `<span><i style="background:${d.borderColor}"></i>${esc(d.label)}</span>`).join("");
    this.bw.data.datasets[0].data = s.bw_series.map(p => ({ x: p[0], y: mbps(p[1]) }));
    this.bw.data.datasets[1].data = s.bw_series.map(p => ({ x: p[0], y: mbps(p[2]) }));
    this.bw.update("none");

    $("#targets").innerHTML = s.targets.map(t => `<div class="row" style="padding:9px 0;border-bottom:1px solid var(--border)">
      <span class="dot ${t.last == null ? "bad" : "good"}"></span><div class="grow ellipsis"><b>${esc(t.name)}</b></div>
      <span class="num" style="width:62px;text-align:right">${fmtMs(t.last)} ms</span>
      <span class="pill ${!isNum(t.loss) ? "" : t.loss === 0 ? "good" : t.loss < 5 ? "warn" : "bad"}" style="width:62px;justify-content:center">${isNum(t.loss) ? t.loss.toFixed(0) : "—"}% loss</span></div>`).join("") || `<div class="empty">Waiting for data…</div>`;

    // devices donut
    const types = Object.entries(s.devices.types || {}).sort((a, b) => b[1] - a[1]);
    this.dev.data.labels = types.map(t => TYPE_LABEL[t[0]] || t[0]);
    this.dev.data.datasets[0].data = types.map(t => t[1]);
    this.dev.update("none");
    $("#devCenter").innerHTML = `<div><div class="kpi-value">${s.devices.online}</div><div class="small muted">online</div></div>`;
    $("#devLegend").innerHTML = types.slice(0, 6).map((t, i) => `<div class="row small" style="padding:3px 0"><i style="width:9px;height:9px;border-radius:3px;background:${SERIES[i % SERIES.length]}"></i><span class="grow">${TYPE_LABEL[t[0]] || t[0]}</span><b>${t[1]}</b></div>`).join("") +
      `<div class="small muted" style="margin-top:8px">${plural(s.devices.known, "known device")}${s.devices.new ? ` · <span class="good-t">${s.devices.new} new</span>` : ""}</div>`;

    // speed card
    const sp = s.speed.result;
    $("#speedCard").innerHTML = `<div class="card-head"><div class="card-title">${icon("speed")}Last speed test</div><button class="btn sm" onclick="go('speed')">${s.speed.running ? "Running…" : "Run test"}</button></div>` +
      (sp ? `<div class="grid g-2" style="gap:10px">
        <div><div class="kpi-label">${icon("down", "").replace("<svg", '<svg style="width:12px;height:12px;vertical-align:-1px"')} Download</div><div class="kpi-value">${fmtMbps(sp.down)}<small>Mbps</small></div>${plan.down ? `<div class="progress mt" style="margin-top:6px"><span style="width:${Math.min(100, 100 * sp.down / plan.down)}%"></span></div><div class="kpi-foot">${(100 * sp.down / plan.down).toFixed(0)}% of plan</div>` : ""}</div>
        <div><div class="kpi-label">Upload</div><div class="kpi-value">${fmtMbps(sp.up)}<small>Mbps</small></div>${plan.up ? `<div class="progress" style="margin-top:6px"><span style="width:${Math.min(100, 100 * sp.up / plan.up)}%"></span></div><div class="kpi-foot">${(100 * sp.up / plan.up).toFixed(0)}% of plan</div>` : ""}</div></div>
        <div class="row small muted" style="margin-top:12px">${icon("clock", "").replace("<svg", '<svg style="width:13px;height:13px"')} ${fmtAgo(sp.ts)} · ping ${fmtMs(sp.ping)} ms · ${esc(sp.server || "")}</div>`
        : `<div class="empty" style="padding:20px">No speed tests yet</div>`);

    // health card
    const items = [
      ["Internet", s.internet_up ? "Online" : s.internet_up === false ? "Down" : "…", s.internet_up ? "good" : s.internet_up === false ? "bad" : ""],
      ["Router", isNum(s.router) ? fmtMs(s.router) + " ms" : s.net.gateway ? "No reply" : "Not found", isNum(s.router) ? "good" : "bad"],
      ["Services", `${s.services.up}/${s.services.total} up`, s.services.down ? "bad" : "good"],
      ["Wi-Fi", wifi ? `${fmtMs(wifi.signal)}% · ch ${wifi.channel}` : (s.wifi ? "Disconnected" : "Wired / n/a"), wifi ? (wifi.signal >= 35 ? "good" : "warn") : ""],
      ["Adapter", esc(s.net.interface || "—") + (s.net.link_speed ? ` · ${s.net.link_speed >= 1000 ? s.net.link_speed / 1000 + " Gbps" : s.net.link_speed + " Mbps"}` : ""), ""],
      ["VPN", (s.extra && s.extra.vpn && s.extra.vpn.length) ? "Connected" : "Off", (s.extra && s.extra.vpn && s.extra.vpn.length) ? "good" : ""],
      ["Untrusted devices", (s.extra && s.extra.untrusted_online) ? `${s.extra.untrusted_online} online` : "None", (s.extra && s.extra.untrusted_online) ? "warn" : "good"],
      ["Alerts", s.alerts_paused ? "Paused" : (s.extra && s.extra.quiet) ? "Quiet hours" : "Active", s.alerts_paused || (s.extra && s.extra.quiet) ? "warn" : "good"],
    ];
    $("#healthCard").innerHTML = `<div class="card-head"><div class="card-title">${icon("shield")}Health check</div></div>` +
      items.map(([k, v, c]) => `<div class="row between" style="padding:7px 0;border-bottom:1px solid var(--border)"><span class="muted">${k}</span><span class="pill ${c}">${v}</span></div>`).join("");
    $("#recentEvents").innerHTML = eventList(s.events.slice(0, 5));
    const ex = s.extra || {}, q = ex.quality;
    const qc = r => ({ Excellent: COL.good, Good: COL.good, Fair: COL.warn, Poor: COL.bad, Bad: COL.bad, "4K": COL.good, HD: COL.good, SD: COL.warn, Low: COL.bad }[r] || "#94a3b8");
    const u = ex.usage;
    $("#qualityRow").innerHTML = [
      kpi({ label: "Video calls", value: q ? q.calls : "—", foot: q ? `MOS ${q.mos.toFixed(2)} / 4.5 · Teams, Zoom, FaceTime` : "Waiting for data", pct: q ? (q.mos - 1) / 3.5 : 0, color: qc(q && q.calls), ic: "phone2" }),
      kpi({ label: "Online gaming", value: q ? q.gaming : "—", foot: "Based on latency, jitter and loss", pct: q ? ({ Excellent: 1, Good: .75, Fair: .5, Poor: .25 }[q.gaming] || 0) : 0, color: qc(q && q.gaming), ic: "console" }),
      kpi({ label: "Streaming", value: q && q.streaming ? q.streaming : "—", foot: q && q.streaming ? "Best quality your last speed test supports" : "Run a speed test", pct: q && q.streaming ? ({ "4K": 1, HD: .7, SD: .4, Low: .15 }[q.streaming]) : 0, color: qc(q && q.streaming), ic: "tv" }),
      kpi({ label: "Data this cycle", value: u ? fmtBytes(u.mtd) : "—", foot: u ? (u.cap ? `${u.pct.toFixed(0)}% of ${fmtBytes(u.cap)} allowance` : `Today ${fmtBytes(((u.today || {}).down || 0) + ((u.today || {}).up || 0))}`) : "", pct: u && u.cap ? u.pct / 100 : 0.5, color: u && u.pct > 90 ? COL.bad : u && u.pct > 75 ? COL.warn : COL.teal, ic: "usage" }),
    ].join("");
  },
};
function eventList(evs) {
  if (!evs.length) return `<div class="empty" style="padding:20px">No events yet</div>`;
  const ic = { ALERT: "alert", WARN: "alert", OK: "check", INFO: "info" };
  return evs.map(e => `<div class="ev"><div class="ev-ic ${e.level}">${icon(ic[e.level] || "info")}</div><div class="grow"><div class="ev-msg">${esc(e.message)}</div><div class="ev-time">${fmtDateTime(e.ts)} · ${esc(e.category)}</div></div></div>`).join("");
}

// ------------------------------------------------------------ Devices
PAGES.devices = {
  view: "grid", q: "", data: null, interval: 3000,
  shell() {
    return head("Devices", "Everything connected to your network", `
      <div class="search">${icon("search")}<input class="input" id="devSearch" placeholder="Search name, IP, vendor…" value="${esc(this.q)}"></div>
      <div class="seg" id="devView">${[["grid", "grid", "Grid"], ["list", "list", "List"], ["map", "map", "Map"], ["timeline", "timeline", "Timeline"]].map(([v, ic, l]) => `<button data-v="${v}" class="${this.view === v ? "on" : ""}">${icon(ic)}${l}</button>`).join("")}</div>
      <button class="btn" id="invBtn">${icon("download")}Export</button>
      <button class="btn primary" id="scanBtn">${icon("refresh")}Scan now</button>`) +
      `<div class="grid g-4" id="devStats"></div><div class="mt" id="devBody"></div>`;
  },
  init() {
    $("#devSearch").oninput = e => { this.q = e.target.value; this.render(); };
    $$("#devView button").forEach(b => b.onclick = () => { this.view = b.dataset.v; $$("#devView button").forEach(x => x.classList.toggle("on", x === b)); this.render(true); });
    $("#scanBtn").onclick = async () => { await API.scan_devices(); toast("Scanning your network…"); this.refresh(); };
    $("#invBtn").onclick = () => {
      openModal(`<h3 style="margin-top:0">Export device inventory</h3><p class="muted">Every device with IP, MAC, manufacturer, open ports and when it was first and last seen.</p>
        <div class="row wrap" style="gap:8px"><button class="btn primary" data-f="xlsx">${icon("file")}Excel workbook</button><button class="btn" data-f="csv">${icon("download")}CSV</button><button class="btn" data-f="html">${icon("file")}Printable page / PDF</button></div>`);
      $$("#modal [data-f]").forEach(b => b.onclick = async () => { const r = await API.export_inventory(b.dataset.f); closeOverlays(); if (r.path) toast("Saved to " + r.path, "good"); else if (r.error) toast(r.error, "bad"); });
    };
  },
  async refresh() { this.data = await API.get_devices(); this.render(); },
  render(force) {
    const d = this.data; if (!d || d.error) return;
    const sc = d.scan;
    const btn = $("#scanBtn");
    btn.innerHTML = sc.running ? `${icon("refresh", "spin")}Scanning ${sc.total ? Math.round(100 * sc.done / sc.total) : 0}%` : `${icon("refresh")}Scan now`;
    btn.disabled = sc.running;
    const devs = d.devices;
    const online = devs.filter(x => x.online), nw = devs.filter(x => x.is_new);
    const risky = devs.filter(x => (x.ports || []).some(p => p.risky));
    $("#devStats").innerHTML = [
      kpi({ label: "Online now", value: online.length, foot: `of ${plural(devs.length, "known device")}`, pct: devs.length ? online.length / devs.length : 0, color: COL.good, ic: "devices" }),
      kpi({ label: "New in last 24h", value: nw.length, foot: nw.length ? "Check you recognise them" : "Nothing new", pct: nw.length ? 1 : 0, color: nw.length ? COL.warn : COL.good, ic: "alert" }),
      kpi({ label: "Network", value: esc(d.net.network || "—"), foot: `Gateway ${esc(d.net.gateway || "—")}`, pct: 1, color: COL.indigo, ic: "network" }),
      kpi({ label: "Last scan", value: sc.last ? fmtClock(sc.last) : "—", foot: sc.running ? "Scanning now…" : (d.vendors_loaded ? "Vendor database ready" : "Downloading vendor database…"), pct: sc.running && sc.total ? sc.done / sc.total : 1, color: COL.cyan, ic: "refresh" }),
    ].join("") ;
    const q = this.q.toLowerCase();
    const list = devs.filter(x => !q || [x.name, x.ip, x.mac, x.hostname, x.vendor, x.display_type].join(" ").toLowerCase().includes(q))
      .sort((a, b) => (b.self - a.self) || (b.gateway - a.gateway) || (b.online - a.online) || ipNum(a.ip) - ipNum(b.ip));
    const body = $("#devBody");
    if (!list.length) { body.innerHTML = `<div class="card empty">${icon("devices")}<div>${devs.length ? "No devices match your search" : "No devices found yet — scanning…"}</div></div>`; return; }
    if (this.view === "grid") {
      body.innerHTML = `<div class="dev-grid">${list.map(x => `<div class="card dev ${x.online ? "" : "offline"}" data-key="${esc(x.key)}">
        <div class="row"><div class="dev-ic">${icon(x.display_type)}</div><div class="grow"><div class="dev-name ellipsis">${esc(devName(x))}</div><div class="dev-meta ellipsis">${esc(x.vendor_short || x.hostname || "Unknown vendor")}</div></div>
        ${x.is_new ? `<span class="pill warn">New</span>` : x.trusted ? `<span title="Trusted" style="color:var(--good)">${icon("vpn").replace("<svg", '<svg style="width:16px;height:16px"')}</span>` : ""}</div>
        <div class="dev-foot"><span class="row" style="gap:6px"><span class="dot ${x.online ? "good" : ""}"></span>${esc(x.ip)}</span><span>${x.online ? (isNum(x.rtt) ? fmtMs(x.rtt) + " ms" : "online") : "seen " + fmtAgo(x.last_seen)}</span></div></div>`).join("")}</div>`;
    } else if (this.view === "list") {
      body.innerHTML = `<div class="card" style="padding:6px 8px"><div class="table-wrap"><table class="t"><tr><th></th><th>Name</th><th>Type</th><th>IP address</th><th>MAC</th><th>Vendor</th><th>Latency</th><th>First seen</th><th>Last seen</th></tr>
        ${list.map(x => `<tr data-key="${esc(x.key)}" style="cursor:pointer;${x.online ? "" : "opacity:.55"}"><td><span class="dot ${x.online ? "good" : ""}"></span></td><td><b>${esc(devName(x))}</b> ${x.is_new ? `<span class="pill warn">New</span>` : ""}</td><td>${TYPE_LABEL[x.display_type] || ""}</td><td class="num">${esc(x.ip)}</td><td class="num muted">${esc(x.mac)}</td><td class="ellipsis" style="max-width:200px">${esc(x.vendor_short)}</td><td class="num">${x.online && isNum(x.rtt) ? fmtMs(x.rtt) + " ms" : ""}</td><td class="muted">${fmtDateTime(x.first_seen)}</td><td class="muted">${fmtAgo(x.last_seen)}</td></tr>`).join("")}</table></div></div>`;
    } else if (this.view === "timeline") {
      if (!force && body.querySelector(".tl-wrap") && Date.now() - (this._tlAt || 0) < 60000) return;
      this._tlAt = Date.now();
      API.get_timeline(this.tlHours || 24).then(t => { if (this.view === "timeline") { body.innerHTML = timelineView(t, this.tlHours || 24); $$("[data-tlh]", body).forEach(b => b.onclick = () => { this.tlHours = +b.dataset.tlh; this._tlAt = 0; this.render(true); }); $$("[data-key]", body).forEach(el => el.onclick = () => this.open(el.dataset.key)); } });
      return;
    } else {
      if (!force && body.querySelector(".map-wrap") && this._mapKeys === list.map(x => x.key + x.online).join()) return;
      this._mapKeys = list.map(x => x.key + x.online).join();
      body.innerHTML = `<div class="card map-wrap">${networkMap(list, d.net)}</div>`;
    }
    $$("[data-key]", body).forEach(el => el.onclick = () => this.open(el.dataset.key));
  },
  open(key) {
    const x = this.data.devices.find(d => d.key === key); if (!x) return;
    const web = (x.ports || []).find(p => [80, 443, 8080, 8443, 5000, 5001, 8123, 32400].includes(p.port));
    openDrawer(`<div class="row" style="gap:14px"><div class="dev-ic" style="width:54px;height:54px">${icon(x.display_type)}</div>
      <div class="grow"><div class="page-title" style="font-size:20px">${esc(devName(x))}</div><div class="row small muted"><span class="dot ${x.online ? "good" : ""}"></span>${x.online ? "Online" : "Offline · last seen " + fmtAgo(x.last_seen)}</div></div>
      <button class="btn ghost" onclick="closeOverlays()">${icon("x")}</button></div>
      <div class="section-title">Details</div>
      <div class="field"><label>Name</label><input class="input" id="dName" value="${esc(x.name || "")}" placeholder="${esc(x.hostname || x.vendor_short || "Give this device a name")}"></div>
      <div class="field"><label>Type</label><select class="input" id="dType"><option value="">Automatic (${TYPE_LABEL[x.type] || "Other"})</option>${DEVICE_TYPES.map(t => `<option value="${t}" ${x.type_override === t ? "selected" : ""}>${TYPE_LABEL[t]}</option>`).join("")}</select></div>
      <div class="kv"><div class="k">IP address</div><div class="v num">${esc(x.ip)}</div><div class="k">MAC address</div><div class="v num">${esc(x.mac || "—")}</div>
      <div class="k">Vendor</div><div class="v">${esc(x.vendor || "Unknown")}</div><div class="k">Hostname</div><div class="v">${esc(x.hostname || "—")}</div>
      <div class="k">Latency</div><div class="v">${x.online && isNum(x.rtt) ? fmtMs(x.rtt) + " ms" : "—"}</div><div class="k">First seen</div><div class="v">${fmtDateTime(x.first_seen)}</div></div>
      <div class="row between mt" style="padding:10px 12px;border:1px solid var(--border);border-radius:12px"><div><b>Trusted device</b><div class="small muted">Untrusted devices are highlighted and reported when they return</div></div><label class="switch"><input type="checkbox" id="dTrust" ${x.trusted ? "checked" : ""}><span></span></label></div>
      <div class="field mt"><label>Notes</label><textarea class="input" id="dNotes" rows="2" placeholder="e.g. Laptop in the study">${esc(x.notes || "")}</textarea></div>
      <div class="row wrap" style="gap:8px"><button class="btn primary" id="dSave">${icon("check")}Save</button><button class="btn" id="dPing">${icon("clock")}Ping</button>
      <button class="btn" id="dPorts">${icon("shield")}Scan ports</button>${x.mac && !x.self ? `<button class="btn" id="dWake">${icon("power")}Wake</button>` : ""}
      ${web ? `<button class="btn" id="dWeb">${icon("external")}Open web page</button>` : ""}</div>
      <div id="dResult" class="mt"></div>
      <div class="section-title">Open ports ${x.ports_ts ? `<span class="muted" style="text-transform:none;letter-spacing:0;font-weight:500">· scanned ${fmtAgo(x.ports_ts)}</span>` : ""}</div>
      <div id="dPortList">${portList(x.ports)}</div>
      <div class="section-title">Device health (SNMP)</div><div id="dSnmp">${snmpView(x.snmp)}</div>
      <button class="btn sm" id="dSnmpBtn" style="margin-top:8px">${icon("refresh")}Read health</button>
      <div class="section-title">Danger zone</div><button class="btn danger" id="dForget">${icon("trash")}Forget this device</button>
      <div class="small muted" style="margin-top:8px">It will be reported as new if it connects again.</div>`);
    $("#dSave").onclick = async () => { await API.update_device(key, { name: $("#dName").value.trim(), notes: $("#dNotes").value, type_override: $("#dType").value, trusted: $("#dTrust").checked }); toast("Device saved", "good"); closeOverlays(); this.refresh(); };
    $("#dPing").onclick = async () => {
      $("#dResult").innerHTML = `<div class="callout">${icon("refresh", "spin")}Pinging ${esc(x.ip)}…</div>`;
      const r = await API.ping_device(key); const ok = (r.rtts || []).filter(isNum);
      $("#dResult").innerHTML = ok.length ? `<div class="callout">${icon("check")}<div><b>${ok.length}/4 replies</b><br>min ${fmtMs(Math.min(...ok))} ms · avg ${fmtMs(ok.reduce((a, b) => a + b, 0) / ok.length)} ms · max ${fmtMs(Math.max(...ok))} ms</div></div>` : `<div class="callout warn">${icon("alert")}No replies — the device may be offline or blocking ping.</div>`;
    };
    $("#dPorts").onclick = async () => {
      $("#dPortList").innerHTML = `<div class="callout">${icon("refresh", "spin")}Checking ${Object.keys({}).length || "common"} ports…</div>`;
      const r = await API.port_scan(key); $("#dPortList").innerHTML = portList(r.ports || []); this.refresh();
    };
    if ($("#dWake")) $("#dWake").onclick = async () => { const r = await API.wake_device(key); r.error ? toast(r.error, "bad") : toast("Wake-on-LAN packet sent", "good"); };
    if ($("#dWeb")) $("#dWeb").onclick = () => API.open_url(`${[443, 8443, 5001].includes(web.port) ? "https" : "http"}://${x.ip}:${web.port}`);
    $("#dSnmpBtn").onclick = async () => { $("#dSnmp").innerHTML = `<div class="callout">${icon("refresh", "spin")}Asking the device…</div>`; const r = await API.snmp_health(key); $("#dSnmp").innerHTML = r.error ? `<div class="callout warn">${icon("alert")}${esc(r.error)}</div>` : snmpView(r); };
    $("#dForget").onclick = async () => { await API.forget_device(key); toast("Device forgotten"); closeOverlays(); this.refresh(); };
  },
};
const ipNum = ip => (ip || "0.0.0.0").split(".").reduce((a, b) => a * 256 + (+b || 0), 0);
const devName = x => x.name || x.hostname || x.vendor_short || x.ip;
function portList(ports) {
  if (ports == null) return `<div class="muted small">Not scanned yet. Click “Scan ports” to see which services this device offers.</div>`;
  if (!ports.length) return `<div class="callout">${icon("shield")}No common ports open — this device isn't offering any services.</div>`;
  const risky = ports.filter(p => p.risky);
  return (risky.length ? `<div class="callout warn" style="margin-bottom:10px">${icon("alert")}<div>${risky.map(p => p.service).join(", ")} ${risky.length > 1 ? "are" : "is"} open. That's normal for a PC sharing files, but unusual for a smart gadget.</div></div>` : "") +
    `<div class="row wrap" style="gap:6px">${ports.map(p => `<span class="pill ${p.risky ? "warn" : "info"}">${p.port} · ${esc(p.service || "unknown")}</span>`).join("")}</div>`;
}
function networkMap(list, net) {
  const W = 1000, H = 600, cx = 500, cy = 330;
  const router = list.find(x => x.gateway);
  const others = list.filter(x => x !== router);
  const n = others.length, rx = n > 14 ? 420 : 360, ry = n > 14 ? 230 : 200;
  const nodes = others.map((x, i) => {
    const a = (-90 + 30) * Math.PI / 180 + (i / Math.max(1, n)) * (300 * Math.PI / 180);
    return { x, px: cx + rx * Math.cos(a + Math.PI / 2 * 0), py: cy + ry * Math.sin(a) };
  });
  const iconSvg = (t, x, y, s, color) => `<svg x="${x - s / 2}" y="${y - s / 2}" width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="${color}" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">${ICONS[t] || ICONS.device}</svg>`;
  const lines = nodes.map(({ x, px, py }) => `<line x1="${cx}" y1="${cy}" x2="${px}" y2="${py}" stroke="${x.online ? "rgba(56,189,248,.35)" : "rgba(148,163,184,.18)"}" stroke-width="1.5" ${x.online ? "" : 'stroke-dasharray="4 5"'}/>`).join("");
  const dots = nodes.map(({ x, px, py }) => `<g class="map-node" data-key="${esc(x.key)}" opacity="${x.online ? 1 : 0.5}">
      <circle class="bg" cx="${px}" cy="${py}" r="25" fill="var(--surface-solid)" stroke="${x.online ? (x.is_new ? COL.warn : "rgba(56,189,248,.6)") : "rgba(148,163,184,.3)"}" stroke-width="1.5"/>
      ${iconSvg(x.display_type, px, py, 22, x.online ? COL.cyan : "#94a3b8")}
      <circle cx="${px + 18}" cy="${py - 18}" r="5" fill="${x.online ? COL.good : "#64748b"}" stroke="var(--surface-solid)" stroke-width="2"/>
      <text x="${px}" y="${py + 42}" text-anchor="middle" fill="var(--text-2)" font-size="12" font-weight="600">${esc(devName(x).slice(0, 18))}</text>
      <text x="${px}" y="${py + 57}" text-anchor="middle" fill="var(--muted)" font-size="10.5">${esc(x.ip)}</text></g>`).join("");
  return `<svg viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet">
    <defs><radialGradient id="rg"><stop offset="0" stop-color="rgba(56,189,248,.35)"/><stop offset="1" stop-color="rgba(56,189,248,0)"/></radialGradient>
    <linearGradient id="lg" x1="0" x2="1" y1="0" y2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="#6366f1"/></linearGradient></defs>
    <line x1="${cx}" y1="${cy - 36}" x2="${cx}" y2="78" stroke="${COL.indigo}" stroke-width="3" stroke-dasharray="2 6" stroke-linecap="round"/>
    <g>${iconSvg("cloud", cx, 52, 46, COL.indigo)}<text x="${cx + 34}" y="57" fill="var(--text-2)" font-size="13" font-weight="600">Internet</text></g>
    ${lines}
    <circle cx="${cx}" cy="${cy}" r="70" fill="url(#rg)"/>
    <g class="map-node" ${router ? `data-key="${esc(router.key)}"` : ""}><circle cx="${cx}" cy="${cy}" r="36" fill="url(#lg)"/>${iconSvg("router", cx, cy, 30, "#fff")}
    <text x="${cx}" y="${cy + 56}" text-anchor="middle" fill="var(--text)" font-size="13" font-weight="700">${esc(router ? devName(router) : "Router")}</text>
    <text x="${cx}" y="${cy + 71}" text-anchor="middle" fill="var(--muted)" font-size="11">${esc(net.gateway || "")}</text></g>
    ${dots}</svg>`;
}

// ------------------------------------------------------------ Apps & traffic
PAGES.apps = {
  interval: 2000, filter: "", tick: 0,
  shell() {
    return head("Apps & traffic", "Which programs on this PC are using the network") +
      `<div id="appsTop"></div>
      <div class="card mt"><div class="card-head"><div class="card-title">${icon("list")}Active connections</div>
      <div class="row"><span class="card-sub" id="connCount"></span><div class="search">${icon("search")}<input class="input" id="connFilter" placeholder="Filter by app, IP, port…"></div></div></div>
      <div class="table-wrap" style="max-height:440px"><table class="t" id="connTable"></table></div></div>`;
  },
  init() { $("#connFilter").oninput = e => { this.filter = e.target.value.toLowerCase(); this.renderConns(); }; },
  async refresh() {
    const a = await API.get_apps();
    if (!a || a.error) return;
    if (this.tick++ % 3 === 0) { this.conns = await API.get_connections(); this.renderConns(); }
    const top = $("#appsTop");
    if (a.available) {
      const max = Math.max(1, ...a.rates.map(r => r.down + r.up));
      if (!top.dataset.mode) {
        top.dataset.mode = "live";
        top.innerHTML = `<div class="grid g-3"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("bolt")}Live bandwidth by app</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Download</span><span><i style="background:${COL.indigo}"></i>Upload</span></div></div><div class="bars-h" id="appBars"></div></div>
          <div class="card"><div class="card-head"><div class="card-title">${icon("history")}Today's top apps</div></div><div style="height:200px"><canvas id="appDonut"></canvas></div><div id="todayList" class="mt"></div></div></div>`;
        this.donut = mkChart($("#appDonut"), { type: "doughnut", data: { labels: [], datasets: [{ data: [], backgroundColor: SERIES, borderWidth: 0, spacing: 2, borderRadius: 4 }] }, options: { cutout: "70%", maintainAspectRatio: false, plugins: { tooltip: { callbacks: { label: it => ` ${it.label}: ${fmtBytes(it.parsed)}` } } } } });
      }
      $("#appBars").innerHTML = a.rates.slice(0, 12).map(r => `<div class="b"><div class="row ellipsis"><div class="avatar" style="background:${avatarColor(r.process)}">${esc(r.process[0] || "?").toUpperCase()}</div><span class="ellipsis">${esc(r.process.replace(/\.exe$/i, ""))}</span></div>
        <div class="track"><span style="width:${100 * r.down / max}%;background:${COL.cyan}"></span><span style="width:${100 * r.up / max}%;background:${COL.indigo}"></span></div>
        <div class="num small" style="text-align:right">${fmtRate(r.down).join(" ")}<br><span class="muted">${fmtRate(r.up).join(" ")} ↑</span></div></div>`).join("") || `<div class="empty" style="padding:24px">No app traffic right now</div>`;
      const today = a.today.slice(0, 8);
      this.donut.data.labels = today.map(t => t.process.replace(/\.exe$/i, ""));
      this.donut.data.datasets[0].data = today.map(t => t.bytes_in + t.bytes_out);
      this.donut.update("none");
      $("#todayList").innerHTML = today.slice(0, 5).map((t, i) => `<div class="row small" style="padding:4px 0"><i style="width:9px;height:9px;border-radius:3px;background:${SERIES[i % SERIES.length]}"></i><span class="grow ellipsis">${esc(t.process)}</span><b class="num">${fmtBytes(t.bytes_in + t.bytes_out)}</b></div>`).join("") || `<div class="muted small">Usage builds up over the day.</div>`;
    } else if (!top.dataset.mode) {
      top.dataset.mode = "basic";
      top.innerHTML = `<div class="grid g-3"><div class="card span-2"><div class="callout warn">${icon("shield")}<div><b>Per-app bandwidth needs administrator rights.</b><br>Windows only exposes per-connection traffic counters to elevated programs. Restart NetWatch as administrator to see live speeds and daily totals for each app. Until then, you can see which apps have open connections.
        ${a.windows ? `<div style="margin-top:12px"><button class="btn primary" id="elevBtn">${icon("shield")}Restart as administrator</button></div>` : ""}</div></div>
        <div class="card-head mt"><div class="card-title">${icon("apps")}Connections by app</div></div><div class="bars-h" id="appConnBars"></div></div>
        <div class="card"><div class="card-head"><div class="card-title">${icon("apps")}Share of connections</div></div><div style="height:260px"><canvas id="appDonut"></canvas></div></div></div>`;
      if ($("#elevBtn")) $("#elevBtn").onclick = async () => { const r = await API.relaunch_admin(); if (r.error) toast(r.error, "bad"); };
      this.donut = mkChart($("#appDonut"), { type: "doughnut", data: { labels: [], datasets: [{ data: [], backgroundColor: SERIES, borderWidth: 0, spacing: 2, borderRadius: 4 }] }, options: { cutout: "68%", maintainAspectRatio: false, plugins: { legend: { display: true, position: "bottom", labels: { boxWidth: 10, boxHeight: 10, useBorderRadius: true, borderRadius: 3 } } } } });
    }
    if (top.dataset.mode === "basic" && this.conns) {
      const by = this.conns.by_process || []; const max = Math.max(1, ...by.map(b => b.count));
      $("#appConnBars").innerHTML = by.slice(0, 8).map(b => `<div class="b"><div class="row ellipsis"><div class="avatar" style="background:${avatarColor(b.process)}">${esc(b.process[0] || "?").toUpperCase()}</div><span class="ellipsis">${esc(b.process.replace(/\.exe$/i, ""))}</span></div><div class="track"><span style="width:${100 * b.count / max}%;background:var(--accent-grad);background:${COL.cyan}"></span></div><div class="num small" style="text-align:right">${plural(b.count, "conn")}</div></div>`).join("");
      this.donut.data.labels = by.slice(0, 7).map(b => b.process.replace(/\.exe$/i, ""));
      this.donut.data.datasets[0].data = by.slice(0, 7).map(b => b.count);
      this.donut.update("none");
    }
  },
  renderConns() {
    if (!this.conns) return;
    const rows = this.conns.rows.filter(r => r.remote && (!this.filter || [r.process, r.remote, r.local, r.status, r.pid].join(" ").toLowerCase().includes(this.filter)))
      .sort((a, b) => a.process.localeCompare(b.process));
    $("#connCount").textContent = `${rows.length} shown`;
    $("#connTable").innerHTML = `<tr><th>App</th><th>PID</th><th>Proto</th><th>Local</th><th>Remote</th><th>State</th></tr>` +
      rows.slice(0, 400).map(r => `<tr><td><div class="row"><div class="avatar" style="width:24px;height:24px;font-size:11px;border-radius:7px;background:${avatarColor(r.process)}">${esc(r.process[0] || "?").toUpperCase()}</div>${esc(r.process)}</div></td><td class="num muted">${r.pid}</td><td>${r.proto}</td><td class="num muted">${esc(r.local)}</td><td class="num">${esc(r.remote)}</td><td><span class="pill ${r.status === "ESTABLISHED" ? "good" : ""}">${esc(r.status || "—")}</span></td></tr>`).join("");
  },
};

// ------------------------------------------------------------ Wi-Fi
PAGES.wifi = {
  interval: 5000,
  shell() { return head("Wi-Fi", "Signal quality, channels and nearby networks") + `<div id="wifiBody"></div>`; },
  async refresh() {
    const w = await API.get_wifi(); if (!w || w.error) return;
    const body = $("#wifiBody");
    if (!w.supported) { body.innerHTML = `<div class="card empty">${icon("wifi")}<div>Wi-Fi details are available on Windows only.</div></div>`; return; }
    if (!w.info) { body.innerHTML = `<div class="card empty">${icon("wifi")}<div><b>No Wi-Fi adapter in use</b><br>This PC looks to be on a wired connection — which is great for reliability.</div></div>`; return; }
    if (w.info.error === "location") { body.innerHTML = `<div class="callout warn">${icon("alert")}<div><b>Windows is blocking Wi-Fi details.</b><br>Recent Windows versions need Location services turned on to read Wi-Fi information. Open <b>Settings → Privacy & security → Location</b>, turn on Location services and allow desktop apps, then come back here.</div></div>`; return; }
    const i = w.info, sig = i.signal || 0;
    if (!body.dataset.ready) {
      body.dataset.ready = 1;
      body.innerHTML = `<div class="grid g-3"><div class="card" id="wifiGauge"></div><div class="card span-2"><div class="card-head"><div class="card-title">${icon("clock")}Signal history</div><div class="legend"><span><i style="background:${COL.good}"></i>Signal %</span><span><i style="background:${COL.indigo}"></i>Link rate</span></div></div><div class="chart-box"><canvas id="sigChart"></canvas></div></div></div>
        <div id="wifiRec"></div>
        <div class="grid g-2 mt"><div class="card"><div class="card-head"><div class="card-title">${icon("grid")}Channel congestion</div><span class="card-sub">networks per channel</span></div><div class="chart-box"><canvas id="chChart"></canvas></div></div>
        <div class="card"><div class="card-head"><div class="card-title">${icon("wifi")}Nearby networks</div><span class="card-sub" id="netCount"></span></div><div class="table-wrap" style="max-height:250px"><table class="t" id="netTable"></table></div></div></div>
        <div class="grid g-2 mt"><div class="card" id="surveyCard"></div><div class="card" id="meshCard"></div></div>`;
      wifiExtras();
      this.sig = timeLine($("#sigChart"), { datasets: [{ label: "Signal", color: COL.good, data: [], fmt: v => v.toFixed(0) + "%" }, { label: "Link rate", color: COL.indigo, data: [], fill: false, yAxisID: "y2", fmt: v => v.toFixed(0) + " Mbps" }], yFmt: v => v + "%", yMax: 100, y2: v => v + " Mbps", tickFmt: fmtClockS });
      this.ch = mkChart($("#chChart"), { type: "bar", data: { labels: [], datasets: [{ data: [], borderRadius: 6, backgroundColor: [] }] }, options: { maintainAspectRatio: false, scales: { x: { grid: { display: false }, title: { display: true, text: "Channel" } }, y: { beginAtZero: true, ticks: { precision: 0 }, grid: { color: cssv("--grid-line") }, border: { display: false } } } } });
    }
    const col = sig >= 60 ? COL.good : sig >= 35 ? COL.warn : COL.bad;
    const quality = sig >= 80 ? "Excellent" : sig >= 60 ? "Good" : sig >= 40 ? "Fair" : "Poor";
    $("#wifiGauge").innerHTML = `<div class="card-head"><div class="card-title">${icon("wifi")}${esc(i.ssid || "Wi-Fi")}</div><span class="pill ${i.connected ? "good" : "bad"}">${i.connected ? "Connected" : esc(i.state || "Disconnected")}</span></div>
      <div class="row" style="gap:20px">${ring(sig / 100, col, null, 120, 12).replace('<div class="icon"></div>', `<div class="icon"><div style="text-align:center"><div class="kpi-value">${fmtMs(sig)}%</div><div class="small muted">${quality}</div></div></div>`)}
      <div class="kv grow" style="grid-template-columns:90px 1fr"><div class="k">Band</div><div class="v">${esc(i.band || "—")}</div><div class="k">Channel</div><div class="v">${esc(i.channel ?? "—")}</div><div class="k">Standard</div><div class="v">${esc(i.radio || "—")}</div><div class="k">RSSI</div><div class="v">${i.rssi ?? "—"} dBm</div></div></div>
      <div class="kv mt" style="grid-template-columns:110px 1fr"><div class="k">Link rate</div><div class="v">${fmtMs(i.rx_rate)} ↓ / ${fmtMs(i.tx_rate)} ↑ Mbps</div><div class="k">Access point</div><div class="v num">${esc(i.bssid || "—")}</div><div class="k">Security</div><div class="v">${esc(i.auth || "—")}</div></div>`;
    this.sig.data.datasets[0].data = w.history.map(h => ({ x: h[0], y: h[1] }));
    this.sig.data.datasets[1].data = w.history.map(h => ({ x: h[0], y: h[2] }));
    this.sig.update("none");
    $("#wifiRec").innerHTML = w.recommendation ? `<div class="callout mt">${icon("info")}<div>${esc(w.recommendation)}</div></div>` : (sig < 40 ? `<div class="callout warn mt">${icon("alert")}<div>Your signal is weak. Moving closer to the router, removing obstructions or adding a mesh point would help.</div></div>` : "");
    this.ch.data.labels = w.channels.map(c => c.channel);
    this.ch.data.datasets[0].data = w.channels.map(c => c.count);
    this.ch.data.datasets[0].backgroundColor = w.channels.map(c => c.channel === i.channel ? COL.cyan : "rgba(129,140,248,.45)");
    this.ch.update("none");
    $("#netCount").textContent = plural(w.networks.length, "access point");
    $("#netTable").innerHTML = `<tr><th>Network</th><th>Signal</th><th>Channel</th><th>Band</th><th>Security</th></tr>` + w.networks.map(n => `<tr style="${n.bssid === i.bssid ? "background:rgba(56,189,248,.08)" : ""}"><td><b>${esc(n.ssid)}</b>${n.bssid === i.bssid ? ` <span class="pill info">You</span>` : ""}</td><td>${signalBars(n.signal)} <span class="num small">${fmtMs(n.signal)}%</span></td><td class="num">${n.channel ?? "—"}</td><td>${esc(n.band || "")}</td><td class="muted">${esc(n.auth || "")}</td></tr>`).join("");
  },
};

// ------------------------------------------------------------ Speed test
const SPEED_STEPS = [0, 5, 10, 25, 50, 100, 250, 500, 1000];
function speedFrac(v) {
  if (!isNum(v) || v <= 0) return 0;
  for (let i = 1; i < SPEED_STEPS.length; i++) if (v <= SPEED_STEPS[i]) return (i - 1 + (v - SPEED_STEPS[i - 1]) / (SPEED_STEPS[i] - SPEED_STEPS[i - 1])) / (SPEED_STEPS.length - 1);
  return 1;
}
function speedometer(value, phase, color) {
  const cx = 190, cy = 175, r = 145, a0 = 135, sweep = 270;
  const pt = (deg, rad) => [cx + rad * Math.cos(deg * Math.PI / 180), cy + rad * Math.sin(deg * Math.PI / 180)];
  const arc = (from, to, rad) => { const [x1, y1] = pt(from, rad), [x2, y2] = pt(to, rad); return `M${x1} ${y1} A${rad} ${rad} 0 ${to - from > 180 ? 1 : 0} 1 ${x2} ${y2}`; };
  const f = speedFrac(value), end = a0 + sweep * f;
  const ticks = SPEED_STEPS.map((s, i) => { const d = a0 + sweep * i / (SPEED_STEPS.length - 1); const [x, y] = pt(d, r - 30); return `<text class="tick" x="${x}" y="${y + 4}" text-anchor="middle">${s}</text>`; }).join("");
  const [nx, ny] = pt(end, r - 46);
  return `<svg class="speedo" viewBox="0 0 380 330"><defs><linearGradient id="sg" x1="0" x2="1"><stop offset="0" stop-color="#22d3ee"/><stop offset="1" stop-color="${color}"/></linearGradient>
    <filter id="glow"><feGaussianBlur stdDeviation="4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <path d="${arc(a0, a0 + sweep, r)}" stroke="var(--grid-line)" stroke-width="16" fill="none" stroke-linecap="round"/>
    ${f > 0.002 ? `<path d="${arc(a0, end, r)}" stroke="url(#sg)" stroke-width="16" fill="none" stroke-linecap="round" filter="url(#glow)"/>` : ""}
    ${ticks}
    <line x1="${cx}" y1="${cy}" x2="${nx}" y2="${ny}" stroke="${color}" stroke-width="3" stroke-linecap="round" opacity="${f > 0 ? 1 : 0}"/>
    <circle cx="${cx}" cy="${cy}" r="6" fill="${color}" opacity="${f > 0 ? 1 : 0}"/>
    <text class="phase" x="${cx}" y="${cy + 52}" text-anchor="middle">${esc(phase)}</text>
    <text class="val" x="${cx}" y="${cy + 108}" text-anchor="middle">${isNum(value) ? fmtMbps(value) : "—"}</text>
    <text class="unit" x="${cx}" y="${cy + 132}" text-anchor="middle">Mbps</text></svg>`;
}
PAGES.speed = {
  interval: 500,
  shell() {
    return head("Speed test", "Measure your real broadband speed and track it against your plan", `<span class="muted small" id="schedInfo"></span>`) +
      `<div class="grid g-3"><div class="card" style="display:flex;flex-direction:column;align-items:center;gap:14px" id="speedMain"></div>
      <div class="card span-2"><div class="card-head"><div class="card-title">${icon("history")}Speed history</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Download</span><span><i style="background:${COL.indigo}"></i>Upload</span><span id="planLegend"></span></div></div><div class="chart-box tall"><canvas id="spChart"></canvas></div></div></div>
      <div class="grid g-4 mt" id="spStats"></div>
      <div class="card mt" id="bloatCard"></div>
      <div class="card mt"><div class="card-head"><div class="card-title">${icon("list")}Recent tests</div></div><div class="table-wrap" style="max-height:320px"><table class="t" id="spTable"></table></div></div>`;
  },
  init() {
    this.chart = timeLine($("#spChart"), { datasets: [{ label: "Download", color: COL.cyan, data: [], spanGaps: true, fmt: v => v.toFixed(1) + " Mbps" }, { label: "Upload", color: COL.indigo, data: [], spanGaps: true, fmt: v => v.toFixed(1) + " Mbps" }], yFmt: v => v + "", dateFmt: ts => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short" }) });
    this.chart.data.datasets.forEach(d => { d.pointRadius = 3; d.pointBackgroundColor = d.borderColor; });
    this.lastHist = "";
  },
  async refresh() {
    const r = await API.get_speedtest(); if (!r || r.error) return;
    const s = r.state, res = s.result, plan = r.plan || {};
    $("#schedInfo").textContent = r.interval ? `Automatic test every ${r.interval} h` : "Automatic tests off";
    const main = $("#speedMain");
    if (s.running) {
      const color = s.phase === "upload" ? COL.indigo : COL.cyan;
      main.innerHTML = `<div class="speedo-wrap">${speedometer(s.phase === "latency" ? 0 : s.mbps, s.phase === "latency" ? "Measuring ping" : s.phase, color)}</div>
        <div style="width:80%"><div class="progress"><span style="width:${(s.phase === "upload" ? 50 + 50 * s.progress : s.phase === "download" ? 50 * s.progress : 2)}%"></span></div></div>`;
    } else {
      main.innerHTML = `<div class="speedo-wrap" style="position:relative">${speedometer(res ? res.down : null, res ? "Last download" : "Ready", COL.cyan)}</div>
        <button class="go-btn" id="goBtn">GO</button>${s.error ? `<div class="callout warn">${icon("alert")}${esc(s.error)}</div>` : ""}`;
      $("#goBtn").onclick = async () => { await API.start_speedtest(); this.refresh(); };
    }
    $("#spStats").innerHTML = res ? [
      kpi({ label: "Download", value: fmtMbps(res.down), unit: "Mbps", foot: plan.down ? `${(100 * res.down / plan.down).toFixed(0)}% of your ${plan.down} Mbps plan` : "Set your plan in Settings", pct: plan.down ? res.down / plan.down : speedFrac(res.down), color: COL.cyan, ic: "down" }),
      kpi({ label: "Upload", value: fmtMbps(res.up), unit: "Mbps", foot: plan.up ? `${(100 * res.up / plan.up).toFixed(0)}% of your ${plan.up} Mbps plan` : "", pct: plan.up ? res.up / plan.up : speedFrac(res.up), color: COL.indigo, ic: "up" }),
      kpi({ label: "Ping", value: fmtMs(res.ping), unit: "ms", foot: `Jitter ${fmtMs(res.jitter, 1)} ms`, pct: Math.min(1, res.ping / 100), color: latColor(res.ping, 80), ic: "clock" }),
      kpi({ label: "Server", value: `<span style="font-size:17px">${esc(res.server || "—")}</span>`, foot: `${esc(res.isp || "")} · ${fmtAgo(res.ts)}`, pct: 1, color: COL.teal, ic: "globe" }),
    ].join("") : "";
    $("#bloatCard").innerHTML = bloatView(res);
    const key = r.history.map(h => h.ts).join();
    if (key !== this.lastHist) {
      this.lastHist = key;
      const hist = [...r.history].reverse();
      this.chart.data.datasets[0].data = hist.map(h => ({ x: h.ts, y: h.down }));
      this.chart.data.datasets[1].data = hist.map(h => ({ x: h.ts, y: h.up }));
      this.chart.data.datasets.slice(0, 2).forEach(d => { d.pointRadius = hist.length > 40 ? 0 : 3; });
      this.chart.data.datasets = this.chart.data.datasets.slice(0, 2);
      if (plan.down) this.chart.data.datasets.push({ label: "Plan", data: hist.length ? [{ x: hist[0].ts, y: plan.down }, { x: hist[hist.length - 1].ts, y: plan.down }] : [], borderColor: COL.warn, borderDash: [6, 6], borderWidth: 1.5, pointRadius: 0, fill: false, parsing: false });
      $("#planLegend").innerHTML = plan.down ? `<i style="background:${COL.warn}"></i>Plan` : "";
      this.chart.update();
      $("#spTable").innerHTML = `<tr><th>When</th><th>Download</th><th>Upload</th><th>Ping</th><th>Jitter</th><th>Bufferbloat</th><th>Server</th><th>Trigger</th></tr>` + r.history.map(h => `<tr><td>${fmtDateTime(h.ts)}</td><td class="num"><b>${fmtMbps(h.down)}</b> Mbps</td><td class="num">${fmtMbps(h.up)} Mbps</td><td class="num">${fmtMs(h.ping)} ms</td><td class="num">${fmtMs(h.jitter, 1)} ms</td><td>${h.grade ? `<span class="pill ${gradeClass(h.grade)}">${h.grade}</span>` : "—"}</td><td class="muted">${esc(h.server)}</td><td><span class="pill">${esc(h.trigger)}</span></td></tr>`).join("") || `<tr><td colspan="7" class="muted">No tests yet</td></tr>`;
    }
  },
};

// ------------------------------------------------------------ Services
PAGES.services = {
  interval: 5000,
  shell() {
    return head("Services", "Keep an eye on the websites and devices that matter to you", `<button class="btn primary" id="addSvc">${icon("plus")}Add check</button>`) + `<div class="grid g-3" id="svcGrid"></div>`;
  },
  init() { $("#addSvc").onclick = () => this.edit({ type: "http", interval: 60, enabled: true }); },
  async refresh() {
    const list = await API.get_services(); if (!list || list.error) return;
    this.list = list;
    $("#svcGrid").innerHTML = list.map(c => {
      const st = !c.enabled ? "" : c.ok === true ? "good" : c.ok === false ? "bad" : "";
      const strip = [...Array(Math.max(0, 40 - c.hist.length)).fill(null), ...c.hist.slice(-40)];
      return `<div class="card svc"><div class="row"><span class="dot ${st} ${st ? "live" : ""}"></span><div class="grow"><div class="dev-name ellipsis">${esc(c.name)}</div><div class="dev-meta ellipsis">${esc(c.type.toUpperCase())} · ${esc(c.target)}</div></div>
        <span class="pill ${st}">${!c.enabled ? "Paused" : c.ok === true ? "Up" : c.ok === false ? "Down" : "Checking"}</span></div>
        <div class="row between"><div><div class="kpi-value" style="font-size:22px">${fmtMs(c.ms)}<small>ms</small></div><div class="kpi-foot">${isNum(c.uptime) ? c.uptime.toFixed(2) + "% uptime (24h)" : "No data yet"}</div></div>${sparkSvg(c.hist, st === "bad" ? COL.bad : COL.cyan, 130, 40)}</div>
        <div class="uptime-strip">${strip.map(h => h === null ? '<i class="none" style="height:35%"></i>' : `<i class="${h[1] == null ? "bad" : ""}" title="${fmtClock(h[0])}" style="height:${h[1] == null ? 100 : 65}%"></i>`).join("")}</div>
        <div class="row between small muted"><span>${esc(c.detail || "")}</span><span>${c.ts ? fmtAgo(c.ts) : ""}</span></div>
        ${c.cert && isNum(c.cert.days) ? `<div class="row small"><span style="color:${c.cert.days <= 14 ? "var(--bad)" : c.cert.days <= 30 ? "var(--warn)" : "var(--muted)"}">${icon("lock").replace("<svg", '<svg style="width:13px;height:13px;vertical-align:-2px"')} Certificate ${c.cert.days < 0 ? "EXPIRED" : `expires in ${c.cert.days} days`}${c.cert.issuer ? ` · ${esc(c.cert.issuer)}` : ""}</span></div>` : ""}
        <div class="row" style="gap:6px"><button class="btn sm" data-run="${c.id}">${icon("refresh")}Check now</button><button class="btn sm ghost" data-edit="${c.id}">${icon("edit")}Edit</button><button class="btn sm ghost danger" data-del="${c.id}">${icon("trash")}</button></div></div>`;
    }).join("") || `<div class="card empty span-3">${icon("services")}<div>No checks yet. Add a website, server or device to monitor.</div></div>`;
    $$("[data-run]").forEach(b => b.onclick = async () => { await API.run_service_now(b.dataset.run); toast("Checking…"); setTimeout(() => this.refresh(), 2500); });
    $$("[data-edit]").forEach(b => b.onclick = () => this.edit(this.list.find(c => c.id === b.dataset.edit)));
    $$("[data-del]").forEach(b => b.onclick = async () => { await API.delete_service(b.dataset.del); toast("Check removed"); this.refresh(); });
  },
  edit(c) {
    openModal(`<h3 style="margin-top:0">${c.id ? "Edit" : "Add"} check</h3>
      <div class="field"><label>Name</label><input class="input" id="sName" value="${esc(c.name || "")}" placeholder="e.g. Company VPN"></div>
      <div class="field"><label>Type</label><div class="seg" id="sType">${[["http", "Website (HTTP/S)"], ["tcp", "TCP port"], ["ping", "Ping"]].map(([v, l]) => `<button data-v="${v}" class="${c.type === v ? "on" : ""}">${l}</button>`).join("")}</div></div>
      <div class="field"><label>Target</label><input class="input" id="sTarget" value="${esc(c.target || "")}"><div class="hint" id="sHint"></div></div>
      <div class="row" style="gap:14px"><div class="field grow"><label>Check every (seconds)</label><input class="input" id="sInt" type="number" min="15" value="${c.interval || 60}"></div>
      <div class="field"><label>Enabled</label><label class="switch"><input type="checkbox" id="sEn" ${c.enabled !== false ? "checked" : ""}><span></span></label></div></div>
      <div class="row" style="justify-content:flex-end;gap:8px"><button class="btn" onclick="closeOverlays()">Cancel</button><button class="btn primary" id="sSave">Save</button></div>`);
    let type = c.type || "http";
    const hints = { http: "Full address, e.g. https://www.example.com", tcp: "host:port, e.g. nas.local:5000 or gateway:443", ping: "Hostname or IP address, e.g. 192.168.1.20" };
    const setType = t => { type = t; $$("#sType button").forEach(b => b.classList.toggle("on", b.dataset.v === t)); $("#sHint").textContent = hints[t]; };
    $$("#sType button").forEach(b => b.onclick = () => setType(b.dataset.v)); setType(type);
    $("#sSave").onclick = async () => {
      const chk = { id: c.id, name: $("#sName").value.trim() || $("#sTarget").value.trim(), type, target: $("#sTarget").value.trim(), interval: Math.max(15, +$("#sInt").value || 60), enabled: $("#sEn").checked };
      if (!chk.target) return toast("Enter a target", "bad");
      await API.save_service(chk); closeOverlays(); toast("Check saved", "good"); setTimeout(() => this.refresh(), 300);
    };
  },
};

// ------------------------------------------------------------ DNS
PAGES.dns = {
  interval: 5000,
  shell() {
    return head("DNS", "How quickly website names are turned into addresses") + `<div id="dnsRec"></div><div id="dnsFilter"></div><div class="grid g-4" id="dnsCards"></div>
      <div class="grid g-3 mt"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("clock")}Response time</div><div class="legend" id="dnsLegend"></div></div><div class="chart-box"><canvas id="dnsChart"></canvas></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("bolt")}Average (last 10 min)</div></div><div class="chart-box"><canvas id="dnsBar"></canvas></div></div></div>
      <div class="callout mt">${icon("info")}<div>Slow or failing DNS is a common reason the internet “feels slow” even when speed tests look fine. NetWatch queries your own DNS server alongside well-known public ones so you can compare.</div></div>`;
  },
  init() {
    this.chart = timeLine($("#dnsChart"), { datasets: [], yFmt: v => v + " ms", tickFmt: fmtClockS });
    this.bar = mkChart($("#dnsBar"), { type: "bar", data: { labels: [], datasets: [{ data: [], borderRadius: 8, backgroundColor: [] }] }, options: { indexAxis: "y", maintainAspectRatio: false, scales: { x: { beginAtZero: true, grid: { color: cssv("--grid-line") }, border: { display: false }, ticks: { callback: v => v + " ms" } }, y: { grid: { display: false } } } } });
  },
  async refresh() {
    const d = await API.get_dns(); if (!d || d.error) return;
    if (!this._dfAt || Date.now() - this._dfAt > 30000) { this._dfAt = Date.now(); API.get_dnsfilter().then(f => { const el = $("#dnsFilter"); if (el) el.innerHTML = dnsFilterView(f); }); }
    $("#dnsRec").innerHTML = d.failing ? `<div class="callout warn" style="margin-bottom:16px">${icon("alert")}<div><b>Your DNS server isn't answering.</b> Websites may fail to load. Restarting your router often fixes this; otherwise switch to a public DNS such as Cloudflare (1.1.1.1).</div></div>`
      : d.recommendation ? `<div class="callout" style="margin-bottom:16px">${icon("bolt")}<div>${esc(d.recommendation)}</div></div>` : "";
    $("#dnsCards").innerHTML = d.servers.map((s, i) => `<div class="card"><div class="row between"><div><div class="dev-name">${esc(s.label)}</div><div class="dev-meta num">${esc(s.server)}</div></div>${s.system ? `<span class="pill info">In use</span>` : ""}</div>
      <div class="row between" style="margin-top:12px;align-items:flex-end"><div><div class="kpi-value" style="color:${latColor(s.avg, 100)}">${fmtMs(s.avg)}<small>ms</small></div><div class="kpi-foot">${isNum(s.success) ? s.success.toFixed(0) + "% success" : "—"}</div></div>${sparkSvg(s.hist, SERIES[i % SERIES.length], 110, 36)}</div></div>`).join("") || `<div class="card empty span-4">Gathering DNS measurements…</div>`;
    this.chart.data.datasets = d.servers.map((s, i) => ({ label: `${s.label} ${s.system ? "" : "(" + s.server + ")"}`.trim(), data: s.hist.map(h => ({ x: h[0], y: h[1] })), borderColor: SERIES[i % SERIES.length], backgroundColor: "transparent", fill: false, borderWidth: 2, pointRadius: 0, tension: .3, parsing: false }));
    this.chart.update("none");
    $("#dnsLegend").innerHTML = d.servers.map((s, i) => `<span><i style="background:${SERIES[i % SERIES.length]}"></i>${esc(s.label)}</span>`).join("");
    this.bar.data.labels = d.servers.map(s => s.label.replace("Your DNS ", "Yours "));
    this.bar.data.datasets[0].data = d.servers.map(s => s.avg);
    this.bar.data.datasets[0].backgroundColor = d.servers.map((s, i) => SERIES[i % SERIES.length]);
    this.bar.update("none");
  },
};

// ------------------------------------------------------------ Traceroute
PAGES.trace = {
  interval: 700,
  shell() {
    return head("Traceroute", "See every hop between you and a destination, and where delays creep in") +
      `<div class="card"><div class="row wrap" style="gap:10px"><input class="input" id="trHost" placeholder="Website or IP, e.g. bbc.co.uk" style="max-width:340px">
      <button class="btn primary" id="trGo">${icon("play")}Trace route</button><button class="btn" id="trStop" style="display:none">${icon("stop")}Stop</button>
      <div class="row wrap" style="gap:6px;margin-left:auto">${["bbc.co.uk", "google.com", "1.1.1.1", "microsoft.com", "amazon.co.uk"].map(h => `<button class="btn sm ghost" data-h="${h}">${h}</button>`).join("")}</div></div></div>
      <div id="trAnalysis"></div><div class="card mt" id="trBody"><div class="empty">${icon("route")}<div>Enter a destination and press <b>Trace route</b>.</div></div></div>`;
  },
  init() {
    const go = async h => { if (h) $("#trHost").value = h; const r = await API.start_traceroute($("#trHost").value || "bbc.co.uk"); if (r && r.started === false) toast("A trace is already running"); };
    $("#trGo").onclick = () => go(); $("#trHost").onkeydown = e => { if (e.key === "Enter") go(); };
    $$("[data-h]").forEach(b => b.onclick = () => go(b.dataset.h));
    $("#trStop").onclick = () => API.stop_traceroute();
  },
  async refresh() {
    const t = await API.get_traceroute(); if (!t || t.error) return;
    $("#trGo").disabled = t.running; $("#trStop").style.display = t.running ? "" : "none";
    if (!t.target) return;
    if (!$("#trHost").value) $("#trHost").value = t.target;
    $("#trAnalysis").innerHTML = t.error ? `<div class="callout warn mt">${icon("alert")}${esc(t.error)}</div>` : t.analysis ? `<div class="callout mt">${icon("info")}<div>${esc(t.analysis)}</div></div>` : "";
    const max = Math.max(20, ...t.hops.map(h => h.avg || 0));
    let prev = 0, worst = null;
    t.hops.forEach(h => { if (isNum(h.avg)) { const j = h.avg - prev; if (j > 15 && (!worst || j > worst[1])) worst = [h.hop, j]; prev = Math.max(prev, h.avg); } });
    const gw = STATE && STATE.net.gateway;
    $("#trBody").innerHTML = `<div class="card-head"><div class="card-title">${icon("route")}Route to ${esc(t.target)} ${t.dest ? `<span class="muted num">(${esc(t.dest)})</span>` : ""}</div>${t.running ? `<span class="pill info">${icon("refresh", "spin").replace("<svg", '<svg style="width:12px;height:12px"')} Tracing…</span>` : `<span class="pill good">${plural(t.hops.length, "hop")}</span>`}</div>
      <div class="hops">${t.hops.map(h => {
        const cls = !h.ip ? "timeout" : worst && worst[0] === h.hop ? "jump" : (h.avg || 0) > 100 ? "slow" : "ok";
        const tag = h.ip === gw ? `<span class="pill info">Your router</span>` : h.private ? `<span class="pill">Private</span>` : "";
        return `<div class="hop ${cls}"><div class="hop-n">${h.hop}</div><div class="ellipsis"><b class="num">${esc(h.ip || "No reply")}</b> ${tag}<div class="small muted ellipsis">${esc(h.host || (h.ip ? "" : "This hop doesn't answer traceroute probes — that's normal"))}</div></div>
          <div class="hbar"><span style="width:${isNum(h.avg) ? Math.max(2, 100 * h.avg / max) : 0}%"></span></div><div class="num" style="text-align:right"><b>${isNum(h.avg) ? fmtMs(h.avg) + " ms" : "—"}</b>${h.loss ? `<div class="small ${h.loss === 100 ? "muted" : "warn-t"}">${h.loss}% loss</div>` : ""}</div></div>`;
      }).join("")}</div>`;
  },
};

// ------------------------------------------------------------ History & reports
PAGES.history = {
  hours: 24,
  shell() {
    return head("History & reports", "Long-term performance — handy evidence if you need to complain to your ISP", `
      <div class="seg" id="hRange">${[[24, "24 hours"], [168, "7 days"], [720, "30 days"], [2160, "90 days"]].map(([h, l]) => `<button data-h="${h}" class="${this.hours === h ? "on" : ""}">${l}</button>`).join("")}</div>
      <button class="btn" id="hCsv">${icon("download")}Export CSV</button><button class="btn primary" id="hReport">${icon("file")}ISP report</button>`) +
      `<div class="grid g-4" id="hKpis"></div>
      <div class="card mt"><div class="card-head"><div class="card-title">${icon("check")}Availability</div><span class="card-sub" id="availSub"></span></div><div class="chart-box short"><canvas id="hAvail"></canvas></div></div>
      <div class="grid g-2 mt"><div class="card"><div class="card-head"><div class="card-title">${icon("clock")}Latency & packet loss</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Latency</span><span><i style="background:${COL.bad}"></i>Loss %</span></div></div><div class="chart-box"><canvas id="hLat"></canvas></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("bolt")}Bandwidth used</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Download</span><span><i style="background:${COL.indigo}"></i>Upload</span></div></div><div class="chart-box"><canvas id="hBw"></canvas></div></div></div>
      <div class="card mt"><div class="card-head"><div class="card-title">${icon("alert")}Outages</div><span class="card-sub" id="outSub"></span></div><div class="table-wrap" style="max-height:300px"><table class="t" id="hOut"></table></div></div>`;
  },
  init() {
    $$("#hRange button").forEach(b => b.onclick = () => { this.hours = +b.dataset.h; $$("#hRange button").forEach(x => x.classList.toggle("on", x === b)); this.load(); });
    $("#hCsv").onclick = async () => { const r = await API.export_history_csv(this.hours); if (r.path) toast("Saved to " + r.path, "good"); };
    $("#hReport").onclick = async () => { const r = await API.export_report(Math.max(this.hours, 168)); if (r.path) toast("Report saved and opened", "good"); else if (r.error) toast(r.error, "bad"); };
    this.load();
  },
  async load() {
    charts.forEach(c => c.destroy()); charts = [];
    const h = await API.get_history(this.hours); if (!h || h.error) return;
    const s = h.summary;
    const plan = STATE ? STATE.plan : {};
    $("#hKpis").innerHTML = [
      kpi({ label: "Uptime", value: isNum(s.uptime) ? s.uptime.toFixed(2) : "—", unit: "%", foot: `${((s.monitored_min || 0) / 60).toFixed(1)} h monitored`, pct: isNum(s.uptime) ? s.uptime / 100 : 0, color: !isNum(s.uptime) ? "#94a3b8" : s.uptime >= 99.9 ? COL.good : s.uptime >= 99 ? COL.warn : COL.bad, ic: "check" }),
      kpi({ label: "Outages", value: s.outages, foot: s.outages ? `${fmtDur(s.outage_s)} offline${STATE && STATE.extra && window.NW_COST ? ` · cost ≈ £${(window.NW_COST * s.outage_s / 3600).toFixed(0)}` : " in total"}` : "None recorded", pct: s.outages ? 1 : 0.02, color: s.outages ? COL.bad : COL.good, ic: "alert" }),
      kpi({ label: "Average latency", value: fmtMs(s.latency), unit: "ms", foot: `Jitter ${fmtMs(s.jitter, 1)} ms · loss ${isNum(s.loss) ? s.loss.toFixed(2) : "—"}%`, pct: isNum(s.latency) ? Math.min(1, s.latency / 200) : 0, color: latColor(s.latency, 150), ic: "clock" }),
      kpi({ label: "Avg speed (tests)", value: fmtMbps(s.avg_speed_down), unit: "Mbps", foot: plan && plan.down && isNum(s.avg_speed_down) ? `${(100 * s.avg_speed_down / plan.down).toFixed(0)}% of plan · ${h.speedtests.length} tests` : `${h.speedtests.length} tests`, pct: plan && plan.down && s.avg_speed_down ? s.avg_speed_down / plan.down : speedFrac(s.avg_speed_down), color: COL.cyan, ic: "speed" }),
    ].join("");
    const ser = h.series;
    const daily = this.hours >= 168;
    $("#availSub").textContent = daily ? "per day" : "per 5 minutes";
    if (daily) {
      const days = h.days;
      mkChart($("#hAvail"), { type: "bar", data: { labels: days.map(d => new Date(d.date).toLocaleDateString([], { day: "numeric", month: "short" })), datasets: [{ data: days.map(d => d.uptime), borderRadius: 5, backgroundColor: days.map(d => d.uptime == null ? "rgba(148,163,184,.2)" : d.uptime >= 99.9 ? COL.good : d.uptime >= 99 ? COL.warn : COL.bad) }] },
        options: { maintainAspectRatio: false, scales: { y: { min: Math.min(95, ...days.map(d => d.uptime ?? 100)) - 0.5, max: 100, ticks: { callback: v => v + "%" }, grid: { color: cssv("--grid-line") }, border: { display: false } }, x: { grid: { display: false } } }, plugins: { tooltip: { callbacks: { label: it => ` ${it.parsed.y == null ? "not monitored" : it.parsed.y.toFixed(2) + "% uptime"}` } } } } });
    } else {
      mkChart($("#hAvail"), { type: "bar", data: { datasets: [{ data: ser.map(p => ({ x: p.ts, y: p.online == null ? null : 100 * p.online })), backgroundColor: ser.map(p => p.online == null ? "transparent" : p.online >= 0.999 ? COL.good : p.online >= 0.9 ? COL.warn : COL.bad), barPercentage: 1, categoryPercentage: 1, parsing: false }] },
        options: { maintainAspectRatio: false, scales: { x: { type: "linear", grid: { display: false }, ticks: { callback: v => fmtClock(v), maxTicksLimit: 8 } }, y: { min: 0, max: 100, ticks: { callback: v => v + "%", maxTicksLimit: 3 }, grid: { color: cssv("--grid-line") }, border: { display: false } } }, plugins: { tooltip: { callbacks: { title: it => fmtDateTime(it[0].parsed.x), label: it => ` ${it.parsed.y.toFixed(1)}% online` } } } } });
    }
    const dfmt = this.hours > 24 ? (ts => new Date(ts * 1000).toLocaleDateString([], { day: "numeric", month: "short" })) : null;
    timeLine($("#hLat"), { datasets: [{ label: "Latency", color: COL.cyan, data: ser.map(p => ({ x: p.ts, y: p.latency })), fmt: v => v.toFixed(0) + " ms" }, { label: "Loss", color: COL.bad, data: ser.map(p => ({ x: p.ts, y: p.loss })), yAxisID: "y2", fill: false, fmt: v => v.toFixed(2) + "%" }], yFmt: v => v + " ms", y2: v => v + "%", y2max: 5, dateFmt: dfmt });
    timeLine($("#hBw"), { datasets: [{ label: "Download", color: COL.cyan, data: ser.map(p => ({ x: p.ts, y: mbps(p.down) })), fmt: v => fmtMbps(v) + " Mbps" }, { label: "Upload", color: COL.indigo, data: ser.map(p => ({ x: p.ts, y: mbps(p.up) })), fmt: v => fmtMbps(v) + " Mbps" }], yFmt: v => fmtMbps(v), dateFmt: dfmt });
    $("#outSub").textContent = h.outages.length ? `${h.outages.length} in this period` : "";
    $("#hOut").innerHTML = `<tr><th>Started</th><th>Ended</th><th>Duration</th><th>Likely cause</th></tr>` + (h.outages.map(o => `<tr><td>${fmtDay(o.start)} ${fmtClock(o.start)}</td><td>${fmtClock(o.end)}</td><td class="num"><b>${fmtDur(o.duration)}</b></td><td><span class="pill ${/router/i.test(o.cause) ? "warn" : "bad"}">${esc(o.cause || "Unknown")}</span></td></tr>`).join("") || `<tr><td colspan="4" class="muted">No outages in this period 🎉</td></tr>`);
  },
};

// ------------------------------------------------------------ Events
PAGES.events = {
  level: "all", q: "", interval: 5000,
  shell() {
    return head("Events", "Everything NetWatch has noticed", `<div class="seg" id="evLevel">${[["all", "All"], ["ALERT", "Alerts"], ["WARN", "Warnings"], ["OK", "Recoveries"], ["INFO", "Info"]].map(([v, l]) => `<button data-v="${v}" class="${this.level === v ? "on" : ""}">${l}</button>`).join("")}</div>
      <div class="search">${icon("search")}<input class="input" id="evQ" placeholder="Search events…" value="${esc(this.q)}"></div><button class="btn" id="evExport">${icon("download")}Export</button>`) + `<div class="card" id="evBody"></div>`;
  },
  init() {
    $$("#evLevel button").forEach(b => b.onclick = () => { this.level = b.dataset.v; $$("#evLevel button").forEach(x => x.classList.toggle("on", x === b)); this.render(); });
    $("#evQ").oninput = e => { this.q = e.target.value.toLowerCase(); this.render(); };
    $("#evExport").onclick = async () => { const r = await API.export_events(); if (r.path) toast("Saved to " + r.path, "good"); };
  },
  async refresh() { this.data = await API.get_events(800); this.render(); },
  render() {
    if (!Array.isArray(this.data)) return;
    const list = this.data.filter(e => (this.level === "all" || e.level === this.level) && (!this.q || (e.message + e.category).toLowerCase().includes(this.q)));
    if (!list.length) { $("#evBody").innerHTML = `<div class="empty">${icon("events")}<div>No matching events</div></div>`; return; }
    let html = "", day = "";
    for (const e of list.slice(0, 400)) {
      const d = new Date(e.ts * 1000).toDateString();
      if (d !== day) { day = d; html += `<div class="section-title" style="margin-top:${html ? 20 : 0}px">${fmtDay(e.ts)}</div>`; }
      html += eventList([e]).replace(fmtDateTime(e.ts), new Date(e.ts * 1000).toLocaleTimeString());
    }
    $("#evBody").innerHTML = html;
  },
};

// ------------------------------------------------------------ Settings
PAGES.settings = {
  shell() { return head("Settings", "Tune monitoring, alerts and notifications", `<button class="btn primary" id="saveSet">${icon("check")}Save changes</button>`) + `<div id="setBody"><div class="empty">Loading…</div></div>`; },
  async init() {
    const s = await API.get_settings(); this.s = s;
    if (!s || s.error) { $("#setBody").innerHTML = `<div class="callout warn">${icon("alert")}Couldn't load settings: ${esc(s && s.error)}</div>`; return; }
    const r = s.remote, m = s._meta;
    const row = (t, d, c) => `<div class="settings-row"><div class="l"><div class="t">${t}</div><div class="d">${d}</div></div><div class="c">${c}</div></div>`;
    const sw = (id, on) => `<label class="switch"><input type="checkbox" id="${id}" ${on ? "checked" : ""}><span></span></label>`;
    const num = (id, v, w = 110, attrs = "") => `<input class="input num" type="number" id="${id}" value="${v ?? ""}" style="width:${w}px" ${attrs}>`;
    $("#setBody").innerHTML = `
    <div class="grid g-2">
    <div class="card"><div class="card-head"><div class="card-title">${icon("settings")}General</div></div>
      ${row("Theme", "Dark or light appearance", `<div class="seg" id="theme"><button data-v="dark" class="${s.theme !== "light" ? "on" : ""}">Dark</button><button data-v="light" class="${s.theme === "light" ? "on" : ""}">Light</button></div>`)}
      ${row("Start with Windows", m.windows ? "Launch quietly into the system tray when you sign in" : "Windows only", sw("sww", s.start_with_windows))}
      ${row("Keep running in the tray", "Closing the window hides NetWatch instead of quitting", sw("tray", s.minimize_to_tray))}
      ${row("Desktop notifications", "Pop-up alerts for outages and problems", sw("notify", s.notify))}
      ${row("New device alerts", "Notify when an unknown device joins your network", sw("notifyNew", s.notify_new_devices))}
    </div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("clock")}Monitoring</div></div>
      ${row("Ping targets", "Servers used to judge whether the internet is up", `<input class="input" id="targets" value="${esc(s.targets.join(", "))}">`)}
      ${row("Ping interval", "Seconds between checks", num("pingInt", s.ping_interval, 90, 'min="1" max="60"'))}
      ${row("High latency alert", "Warn when average latency exceeds (ms)", num("latThr", s.latency_threshold_ms))}
      ${row("Packet loss alert", "Warn when loss exceeds (%)", num("lossThr", s.loss_threshold_pct))}
      ${row("Device scan", "Minutes between automatic scans (0 = off)", num("scanMin", s.auto_scan_minutes))}
      ${row("Weak Wi-Fi alert", "Warn below this signal % (0 = off)", num("wifiThr", s.wifi_signal_alert))}
      ${row("Extra DNS servers", "Public resolvers to compare against", `<input class="input" id="dnsExtra" value="${esc((s.dns_extra || []).join(", "))}">`)}
    </div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("speed")}Speed test & plan</div></div>
      ${row("Your plan — download", "Advertised download speed (Mbps)", num("planD", s.plan_down_mbps || ""))}
      ${row("Your plan — upload", "Advertised upload speed (Mbps)", num("planU", s.plan_up_mbps || ""))}
      ${row("Automatic speed tests", "Hours between tests (0 = off). Each test uses ~200–500 MB on fast lines.", num("spInt", s.speedtest_interval_hours))}
      ${row("Slow speed alert", "Warn when a test is below this % of your plan", num("spPct", s.speed_alert_pct))}
    </div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("folder")}Data</div></div>
      ${row("Keep history for", "Days of history to keep", num("ret", s.retention_days))}
      ${row("Data folder", esc(m.data_dir), `<button class="btn" id="openData">${icon("folder")}Open</button>`)}
      ${row("Version", `NetWatch ${esc(m.version)}`, `<span class="pill ${m.admin ? "good" : ""}">${m.admin ? "Administrator" : "Standard user"}</span>`)}
    </div>
    </div>
    <div class="card mt"><div class="card-head"><div class="card-title">${icon("bolt")}Remote alerts</div><div class="row"><span class="card-sub">Send</span><select class="input" id="minLevel" style="width:270px">${[["ALERT", "Alerts only (outages, new devices)"], ["WARN", "Alerts and warnings"], ["OK", "Everything incl. recoveries"]].map(([v, l]) => `<option value="${v}" ${r.min_level === v ? "selected" : ""}>${l}</option>`).join("")}</select><button class="btn" id="testRemote">${icon("play")}Send test</button></div></div>
      <div class="grid g-3">
        <div><div class="row between"><b>Email</b>${sw("emEn", r.email_enabled)}</div><div class="mt">
          <div class="field"><label>SMTP server</label><input class="input" id="smtpHost" value="${esc(r.smtp_host)}" placeholder="smtp.office365.com"></div>
          <div class="row" style="gap:10px"><div class="field" style="width:100px"><label>Port</label><input class="input" id="smtpPort" value="${esc(r.smtp_port)}"></div><div class="field grow"><label>Username</label><input class="input" id="smtpUser" value="${esc(r.smtp_user)}"></div></div>
          <div class="field"><label>Password</label><input class="input" type="password" id="smtpPass" value="${esc(r.smtp_password)}"><div class="hint">Stored encrypted with your Windows account. Use an app password for Gmail / Microsoft 365.</div></div>
          <div class="field"><label>Send to</label><input class="input" id="emTo" value="${esc(r.email_to)}" placeholder="you@example.com"></div></div></div>
        <div><div class="row between"><b>Microsoft Teams</b>${sw("tmEn", r.teams_enabled)}</div><div class="mt">
          <div class="field"><label>Workflow webhook URL</label><textarea class="input" id="tmUrl" rows="4" placeholder="https://…logic.azure.com/…">${esc(r.teams_webhook)}</textarea><div class="hint">In Teams: channel ⋯ → Workflows → “Post to a channel when a webhook request is received”, then paste the URL here.</div></div></div></div>
        <div><div class="row between"><b>Phone push (ntfy)</b>${sw("nfEn", r.ntfy_enabled)}</div><div class="mt">
          <div class="field"><label>Topic</label><input class="input" id="nfTopic" value="${esc(r.ntfy_topic)}" placeholder="netwatch-${Math.random().toString(36).slice(2, 8)}"></div>
          <div class="field"><label>Server</label><input class="input" id="nfServer" value="${esc(r.ntfy_server)}"></div>
          <div class="hint">Install the free <b>ntfy</b> app on your phone and subscribe to the same topic. Pick something hard to guess — topics are public.</div></div></div>
      </div></div>`;
    $$("#theme button").forEach(b => b.onclick = () => $$("#theme button").forEach(x => x.classList.toggle("on", x === b)));
    $("#openData").onclick = () => API.open_data_folder();
    $("#saveSet").onclick = () => this.save();
    $("#testRemote").onclick = async () => { toast("Sending test alert…"); const r = await API.test_remote(this.collect()); const res = r.results || {};
      const keys = Object.keys(res); toast(keys.length ? keys.map(k => `${k}: ${res[k]}`).join(" · ") : "Enable at least one channel first", keys.some(k => res[k] !== "sent") ? "bad" : "good"); };
  },
  collect() {
    const v = id => $("#" + id).value, c = id => $("#" + id).checked;
    return {
      theme: $("#theme .on").dataset.v, start_with_windows: c("sww"), minimize_to_tray: c("tray"), notify: c("notify"), notify_new_devices: c("notifyNew"),
      targets: v("targets").split(",").map(x => x.trim()).filter(Boolean), ping_interval: v("pingInt"), latency_threshold_ms: v("latThr"), loss_threshold_pct: v("lossThr"),
      auto_scan_minutes: v("scanMin"), wifi_signal_alert: v("wifiThr"), dns_extra: v("dnsExtra").split(",").map(x => x.trim()).filter(Boolean),
      plan_down_mbps: v("planD"), plan_up_mbps: v("planU"), speedtest_interval_hours: v("spInt"), speed_alert_pct: v("spPct"), retention_days: v("ret"),
      remote: { min_level: v("minLevel"), email_enabled: c("emEn"), smtp_host: v("smtpHost").trim(), smtp_port: +v("smtpPort") || 587, smtp_user: v("smtpUser").trim(), smtp_password: v("smtpPass"), email_to: v("emTo").trim(),
        teams_enabled: c("tmEn"), teams_webhook: v("tmUrl").trim(), ntfy_enabled: c("nfEn"), ntfy_topic: v("nfTopic").trim(), ntfy_server: v("nfServer").trim() || "https://ntfy.sh" },
    };
  },
  async save() {
    const r = await API.save_settings(this.collect());
    if (r.error) return toast(r.error, "bad");
    toast("Settings saved", "good");
  },
};

// ============================================================ boot
// boot is in app3.js
