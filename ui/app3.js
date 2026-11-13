"use strict";
/* NetWatch 3 additions: new pages, helpers, phone login and boot */

// ============================================================ shared helpers
const gradeClass = g => !g ? "" : /^A/.test(g) ? "good" : /^[BC]/.test(g) ? "warn" : "bad";
const statusPill = st => ({ ok: ["good", "OK"], warn: ["warn", "Check"], fail: ["bad", "Problem"], bad: ["bad", "Fix"], info: ["info", "Info"], unknown: ["", "Unknown"], skip: ["", "Skipped"] }[st] || ["", st]);
const statusIcon = st => ({ ok: "check", warn: "alert", fail: "x", bad: "x", info: "info" }[st] || "info");
const smallIcon = (n, px = 14) => icon(n).replace("<svg", `<svg style="width:${px}px;height:${px}px;vertical-align:-2px"`);
function jobSpinner(text) { return `<div class="callout">${icon("refresh", "spin")}<div>${text}</div></div>`; }
async function pollJob(getter, onDone, every = 900) {
  const tick = async () => { const j = await getter(); if (j && j.running) { setTimeout(tick, every); } else onDone(j || {}); };
  tick();
}

function bloatView(res) {
  if (!res || !res.grade) {
    return `<div class="card-head"><div class="card-title">${icon("bolt")}Bufferbloat</div></div><div class="muted">Run a speed test to measure <b>bufferbloat</b> — how much your latency jumps when the line is busy. It's the hidden cause of laggy video calls and games while someone else is downloading.</div>`;
  }
  const max = Math.max(50, res.down_loaded_ms || 0, res.up_loaded_ms || 0, res.idle_ms || 0);
  const bar = (label, v, c) => `<div class="b"><span>${label}</span><div class="track"><span style="width:${isNum(v) ? Math.max(2, 100 * v / max) : 0}%;background:${c}"></span></div><span class="num" style="text-align:right">${fmtMs(v)} ms</span></div>`;
  const msg = { "A+": "Superb — your latency barely moves under load.", A: "Very good — calls and games stay smooth while the line is busy.", B: "Good, but heavy downloads can cause brief lag.", C: "Noticeable — video calls may stutter when someone is downloading.", D: "Poor — expect lag spikes during uploads/downloads.", F: "Severe — the connection becomes unusable for real-time apps when busy." }[res.grade] || "";
  return `<div class="card-head"><div class="card-title">${icon("bolt")}Bufferbloat</div><span class="card-sub">latency while the line is busy</span></div>
    <div class="row" style="gap:26px;align-items:center"><div class="grade ${gradeClass(res.grade)}">${res.grade}</div>
    <div class="grow"><div class="bars-h">${bar("Idle", res.idle_ms, COL.good)}${bar("During download", res.down_loaded_ms, COL.cyan)}${bar("During upload", res.up_loaded_ms, COL.indigo)}</div>
    <div class="muted small" style="margin-top:8px">${msg}${/[CDF]/.test(res.grade) ? " Turning on <b>SQM / Smart Queue</b> or QoS in your router settings is the usual fix." : ""}</div></div></div>`;
}

function snmpView(info) {
  if (!info) return `<div class="muted small">Not read yet. Works with printers and NAS drives that have SNMP switched on (community name set in Settings → Integrations).</div>`;
  let h = `<div class="kv"><div class="k">Name</div><div class="v">${esc(info.name || "—")}</div><div class="k">System</div><div class="v small">${esc((info.description || "—").slice(0, 160))}</div>
    <div class="k">Up for</div><div class="v">${info.uptime_s ? fmtDur(info.uptime_s) : "—"}</div>${info.system_temp_c != null ? `<div class="k">Temperature</div><div class="v">${info.system_temp_c} °C</div>` : ""}</div>`;
  if (info.supplies && info.supplies.length) h += `<div class="small muted" style="margin:12px 0 4px">Supplies</div><div class="bars-h">${info.supplies.map(s => `<div class="b" style="grid-template-columns:150px 1fr 50px"><span class="ellipsis">${esc(s.name)}</span><div class="track"><span style="width:${s.percent ?? 0}%;background:${(s.percent ?? 100) < 15 ? COL.bad : (s.percent ?? 100) < 30 ? COL.warn : COL.cyan}"></span></div><span class="num">${s.percent == null ? "?" : s.percent + "%"}</span></div>`).join("")}</div>`;
  if (info.disks && info.disks.length) h += `<div class="small muted" style="margin:12px 0 4px">Disks</div>${info.disks.map(d => `<div class="row between small" style="padding:4px 0"><span>${esc(d.name)}</span><span><span class="pill ${d.status === "Normal" ? "good" : "warn"}">${esc(d.status || "?")}</span> ${d.temp_c} °C</span></div>`).join("")}`;
  if (info.volumes && info.volumes.length) h += `<div class="small muted" style="margin:12px 0 4px">Storage</div><div class="bars-h">${info.volumes.map(v => `<div class="b" style="grid-template-columns:120px 1fr 120px"><span class="ellipsis">${esc(v.name)}</span><div class="track"><span style="width:${v.percent}%;background:${v.percent > 90 ? COL.bad : v.percent > 75 ? COL.warn : COL.teal}"></span></div><span class="num small">${fmtBytes(v.used)} / ${fmtBytes(v.total)}</span></div>`).join("")}</div>`;
  return h + `<div class="small muted" style="margin-top:6px">Read ${fmtAgo(info.ts)}</div>`;
}

function timelineView(t, hours) {
  const span = t.until - t.since, n = hours > 24 ? 168 : 144, bucket = span / n;
  const ticks = [];
  for (let i = 0; i <= 6; i++) { const ts = t.since + span * i / 6; ticks.push(`<span style="position:absolute;left:${100 * i / 6}%;transform:translateX(${i === 0 ? 0 : i === 6 ? -100 : -50}%)">${hours > 24 ? fmtDay(ts) : fmtClock(ts)}</span>`); }
  const rows = t.devices.slice(0, 60).map(d => {
    const on = new Array(n).fill(false);
    d.points.forEach(p => { const i = Math.min(n - 1, Math.floor((p - t.since) / bucket)); if (i >= 0) on[i] = true; });
    let rects = "", i = 0;
    while (i < n) { if (on[i]) { let j = i; while (j < n && on[j]) j++; rects += `<rect x="${(100 * i / n).toFixed(3)}%" y="3" width="${(100 * (j - i) / n).toFixed(3)}%" height="14" rx="3" fill="${d.trusted ? COL.good : COL.cyan}"/>`; i = j; } else i++; }
    const pct = Math.round(100 * on.filter(Boolean).length / n);
    return `<div class="tl-row" data-key="${esc(d.key)}"><div class="row ellipsis" style="gap:8px"><span class="dot ${d.online ? "good" : ""}"></span>${smallIcon(d.type, 15)}<span class="ellipsis">${esc(d.name)}</span></div>
      <svg class="tl-bar" preserveAspectRatio="none"><rect x="0" y="3" width="100%" height="14" rx="3" fill="var(--grid-line)"/>${rects}</svg><span class="num small muted">${pct}%</span></div>`;
  }).join("");
  return `<div class="card tl-wrap"><div class="card-head"><div class="card-title">${icon("timeline")}When devices were online</div>
    <div class="row"><span class="legend"><span><i style="background:${COL.good}"></i>Trusted</span><span><i style="background:${COL.cyan}"></i>Not trusted</span></span>
    <div class="seg">${[[24, "24 hours"], [168, "7 days"]].map(([h, l]) => `<button data-tlh="${h}" class="${hours === h ? "on" : ""}">${l}</button>`).join("")}</div></div></div>
    ${rows ? `<div class="tl-row" style="cursor:default"><span></span><div class="tl-axis">${ticks.join("")}</div><span></span></div>${rows}` : `<div class="empty">Presence history builds up as NetWatch runs (checked every 2 minutes).</div>`}</div>`;
}

function dnsFilterView(f) {
  if (!f || !f.enabled) return `<div class="callout" style="margin-bottom:16px">${icon("shield")}<div>Run <b>Pi-hole</b> or <b>AdGuard Home</b>? Connect it in <a href="#settings">Settings → Integrations</a> to see blocked ads and trackers here.</div></div>`;
  if (f.error) return `<div class="callout warn" style="margin-bottom:16px">${icon("alert")}<div>Couldn't reach your ad blocker: ${esc(f.error)}</div></div>`;
  const maxB = Math.max(1, ...f.top_blocked.map(x => x.count)), maxC = Math.max(1, ...f.top_clients.map(x => x.count));
  return `<div class="grid g-3" style="margin-bottom:16px">
    <div class="card"><div class="card-head"><div class="card-title">${icon("shield")}${esc(f.kind)}</div><span class="pill good">Connected</span></div>
      <div class="row" style="gap:18px">${ring((f.percent || 0) / 100, COL.good, null, 96, 10).replace('<div class="icon"></div>', `<div class="icon"><div style="text-align:center"><div class="kpi-value" style="font-size:20px">${(f.percent || 0).toFixed(1)}%</div><div class="small muted">blocked</div></div></div>`)}
      <div class="kv grow" style="grid-template-columns:110px 1fr"><div class="k">Queries</div><div class="v num">${(f.queries || 0).toLocaleString()}</div><div class="k">Blocked</div><div class="v num">${(f.blocked || 0).toLocaleString()}</div>${f.domains_on_list ? `<div class="k">On blocklists</div><div class="v num">${f.domains_on_list.toLocaleString()}</div>` : ""}</div></div></div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("x")}Top blocked</div></div><div class="bars-h">${f.top_blocked.slice(0, 7).map(x => `<div class="b" style="grid-template-columns:1fr 90px 60px"><span class="ellipsis small">${esc(x.domain)}</span><div class="track"><span style="width:${100 * x.count / maxB}%;background:${COL.bad}"></span></div><span class="num small" style="text-align:right">${x.count}</span></div>`).join("") || '<div class="muted small">Nothing yet</div>'}</div></div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("devices")}Busiest devices</div></div><div class="bars-h">${f.top_clients.slice(0, 7).map(x => `<div class="b" style="grid-template-columns:1fr 90px 60px"><span class="ellipsis small">${esc(x.name)}</span><div class="track"><span style="width:${100 * x.count / maxC}%;background:${COL.cyan}"></span></div><span class="num small" style="text-align:right">${x.count}</span></div>`).join("")}</div></div></div>`;
}

async function wifiExtras() {
  const renderSurvey = rooms => {
    const el = $("#surveyCard"); if (!el) return;
    el.innerHTML = `<div class="card-head"><div class="card-title">${icon("map")}Room-by-room survey</div><span class="card-sub">find the dead spots</span></div>
      <div class="row" style="gap:8px"><input class="input" id="svRoom" placeholder="Where are you? e.g. Kitchen" style="max-width:260px"><button class="btn primary" id="svGo">${icon("record")}Measure here</button></div>
      <div class="small muted" style="margin:8px 0 12px">Carry this laptop to each room and press Measure (takes ~8 seconds).</div>
      <div class="tiles">${rooms.sort((a, b) => b.signal - a.signal).map(r => `<div class="tile" style="--c:${r.signal >= 60 ? COL.good : r.signal >= 35 ? COL.warn : COL.bad}"><div class="row between"><b class="ellipsis">${esc(r.room)}</b><button class="btn ghost sm" data-del="${esc(r.room)}" style="padding:2px">${smallIcon("x", 13)}</button></div>
        <div class="kpi-value" style="font-size:24px">${r.signal}<small>%</small></div><div class="small muted">${r.rx_rate ? r.rx_rate + " Mbps link · " : ""}${r.router_ms != null ? r.router_ms + " ms to router" : ""}</div><div class="small muted">${esc(r.band || "")}${r.channel ? " · ch " + r.channel : ""}</div></div>`).join("") || '<div class="muted small">No rooms measured yet.</div>'}</div>`;
    $("#svGo").onclick = async () => {
      const room = $("#svRoom").value.trim(); if (!room) return toast("Enter a room name", "bad");
      $("#svGo").disabled = true; $("#svGo").innerHTML = `${icon("refresh", "spin")}Measuring…`;
      const r = await API.survey_record(room); if (r.error) toast(r.error, "bad"); else toast(`${room}: ${r.record.signal}% signal`, "good");
      renderSurvey((await API.get_survey()).rooms || []);
    };
    $$("[data-del]", el).forEach(b => b.onclick = async () => { await API.survey_delete(b.dataset.del); renderSurvey((await API.get_survey()).rooms || []); });
  };
  renderSurvey((await API.get_survey()).rooms || []);
  const m = await API.get_mesh(); const el = $("#meshCard"); if (!el || !m || m.error) return;
  el.innerHTML = `<div class="card-head"><div class="card-title">${icon("network")}Access points & roaming</div><span class="card-sub">${plural(m.aps.length, "access point")} seen</span></div>
    <div class="table-wrap" style="max-height:200px"><table class="t"><tr><th>Access point</th><th>Network</th><th>Ch</th><th>Avg signal</th><th>Time on it</th><th>Last used</th></tr>${m.aps.map(a => `<tr><td class="num">${esc(a.bssid)} ${a.current ? '<span class="pill info">Now</span>' : ""}</td><td>${esc(a.ssid || "")}</td><td class="num">${a.channel ?? ""}</td><td class="num">${isNum(a.avg_signal) ? a.avg_signal.toFixed(0) + "%" : "—"}</td><td class="num">${a.minutes >= 60 ? (a.minutes / 60).toFixed(1) + " h" : a.minutes + " min"}</td><td class="muted">${fmtAgo(a.last_seen)}</td></tr>`).join("") || '<tr><td colspan="6" class="muted">Builds up as you use Wi-Fi</td></tr>'}</table></div>
    <div class="small muted" style="margin:12px 0 6px">Roaming in the last 7 days: <b>${m.roams.length}</b> switch${m.roams.length === 1 ? "" : "es"}${m.roams.length > 20 ? " — frequent roaming can mean mesh points are too far apart or overlapping badly." : ""}</div>
    <div style="max-height:110px;overflow:auto">${m.roams.slice(0, 12).map(r => `<div class="row small" style="padding:3px 0"><span class="muted" style="width:120px">${fmtDateTime(r.ts)}</span><span class="num grow ellipsis">${esc(r.from)} → ${esc(r.to)}</span><span class="muted">ch ${r.channel ?? "?"} · ${fmtMs(r.signal)}%</span></div>`).join("")}</div>`;
}

// ============================================================ Usage
PAGES.usage = {
  shell() { return head("Data usage", "How much data flows through this PC, and what's awake overnight") + `<div id="usTop" class="grid g-4"></div>
    <div class="grid g-3 mt"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("usage")}Daily usage</div><div class="legend"><span><i style="background:${COL.cyan}"></i>Download</span><span><i style="background:${COL.indigo}"></i>Upload</span></div></div><div class="chart-box tall"><canvas id="usChart"></canvas></div></div>
    <div class="card"><div class="card-head"><div class="card-title">${icon("apps")}Top apps today</div></div><div id="usApps"></div></div></div>
    <div class="grid g-2 mt"><div class="card" id="overnight"></div><div class="card" id="failovers"></div></div>`; },
  async init() {
    const u = await API.get_usage(); if (!u || u.error) return;
    const dleft = Math.max(0, (u.cycle_end - Date.now() / 1000) / 86400);
    $("#usTop").innerHTML = [
      kpi({ label: "This billing cycle", value: fmtBytes(u.mtd), foot: u.cap ? `${u.pct.toFixed(0)}% of ${fmtBytes(u.cap)}` : "No data cap set", pct: u.cap ? u.pct / 100 : 0.5, color: u.pct > 90 ? COL.bad : u.pct > 75 ? COL.warn : COL.teal, ic: "usage" }),
      kpi({ label: "Projected", value: fmtBytes(u.projected), foot: `by ${new Date(u.cycle_end * 1000).toLocaleDateString([], { day: "numeric", month: "short" })} · ${dleft.toFixed(0)} days left`, pct: u.cap ? Math.min(1, u.projected / u.cap) : 0.5, color: u.cap && u.projected > u.cap ? COL.bad : COL.indigo, ic: "history" }),
      kpi({ label: "Today", value: fmtBytes(u.today ? u.today.down + u.today.up : 0), foot: u.today ? `${fmtBytes(u.today.down)} ↓ · ${fmtBytes(u.today.up)} ↑` : "", pct: 0.5, color: COL.cyan, ic: "down" }),
      kpi({ label: "Last 7 days", value: fmtBytes(u.week_bytes), foot: `≈ ${fmtBytes(u.week_bytes / 7)} per day`, pct: 0.5, color: COL.violet, ic: "clock" }),
    ].join("");
    const days = u.days.slice(-31);
    mkChart($("#usChart"), { type: "bar", data: { labels: days.map(d => new Date(d.date).toLocaleDateString([], { day: "numeric", month: "short" })), datasets: [{ label: "Download", data: days.map(d => d.down / 1e9), backgroundColor: COL.cyan, borderRadius: 4, stack: "a" }, { label: "Upload", data: days.map(d => d.up / 1e9), backgroundColor: COL.indigo, borderRadius: 4, stack: "a" }] },
      options: { maintainAspectRatio: false, scales: { x: { stacked: true, grid: { display: false } }, y: { stacked: true, ticks: { callback: v => v + " GB" }, grid: { color: cssv("--grid-line") }, border: { display: false } } }, plugins: { tooltip: { callbacks: { label: it => ` ${it.dataset.label}: ${it.parsed.y.toFixed(2)} GB` } } } } });
    const maxA = Math.max(1, ...u.apps_today.map(a => a.bytes_in + a.bytes_out));
    $("#usApps").innerHTML = u.apps_today.length ? `<div class="bars-h">${u.apps_today.slice(0, 9).map(a => `<div class="b" style="grid-template-columns:1fr 100px 70px"><span class="ellipsis small">${esc(a.process.replace(/\.exe$/i, ""))}</span><div class="track"><span style="width:${100 * (a.bytes_in + a.bytes_out) / maxA}%;background:${COL.teal}"></span></div><span class="num small" style="text-align:right">${fmtBytes(a.bytes_in + a.bytes_out)}</span></div>`).join("")}</div>` : `<div class="muted small">Per-app totals need NetWatch running as administrator.</div>`;
    $("#failovers").innerHTML = `<div class="card-head"><div class="card-title">${icon("route")}Backup connection</div><span class="card-sub">last 30 days</span></div>` + (u.failovers.length ? u.failovers.map(f => `<div class="row between" style="padding:7px 0;border-bottom:1px solid var(--border)"><span>${fmtDay(f.start)} ${fmtClock(f.start)}</span><span class="pill warn">${esc(f.isp)}</span><b class="num">${fmtDur(f.duration)}</b></div>`).join("") : `<div class="muted">No switches to a backup line detected. If your router fails over to 4G/5G, NetWatch notices the ISP change and records how long you were on it.</div>`) + `<div class="small muted" style="margin-top:12px">${esc(u.note)}</div>`;
    const o = await API.get_overnight();
    $("#overnight").innerHTML = `<div class="card-head"><div class="card-title">${icon("moon")}Overnight activity</div><span class="card-sub">1am – 5am last night</span></div>` + (!o.monitored ? `<div class="muted">No data for last night yet — NetWatch needs to be running overnight.</div>` :
      `<div class="muted small" style="margin-bottom:10px">This PC moved <b>${fmtBytes(o.pc_traffic)}</b> overnight. Devices awake most of the night:</div>` +
      (o.devices.length ? o.devices.slice(0, 10).map(d => `<div class="row" style="padding:6px 0;border-bottom:1px solid var(--border)">${smallIcon(d.type, 16)}<span class="grow ellipsis">${esc(d.name)}</span><div class="progress" style="width:120px"><span style="width:${d.pct}%"></span></div><span class="num small" style="width:42px;text-align:right">${d.pct}%</span></div>`).join("") : `<div class="muted">Nothing stayed online overnight.</div>`));
  },
};

// ============================================================ Security
PAGES.security = {
  interval: 2500,
  shell() { return head("Security", "Spot exposed ports, intruders and risky settings", `<button class="btn primary" id="secAll">${icon("shield")}Run all checks</button>`) +
    `<div class="grid g-3" id="secTop"></div>
    <div class="grid g-2 mt"><div class="card" id="secUpnp"></div><div class="card" id="secExposure"></div></div>
    <div class="grid g-2 mt"><div class="card" id="secPc"></div><div class="card" id="secNet"></div></div>
    <div class="grid g-2 mt"><div class="card" id="secVpn"></div><div class="card" id="secCap"></div></div>`; },
  init() {
    if (!PAGES.devices.data) API.get_devices().then(d => { if (d && !d.error) PAGES.devices.data = d; });
    $("#secAll").onclick = async () => { for (const k of ["pc", "upnp", "exposure"]) await API.run_security(k); toast("Running security checks…"); this.refresh(); };
    API.get_security().then(v => { if (!v || v.error) return; [["pc", v.pc_job], ["upnp", v.upnp_job], ["exposure", v.exposure_job]].forEach(([k, j]) => { if (!j.running && !j.result) API.run_security(k); }); });
  },
  async refresh() {
    const v = await API.get_security(); if (!v || v.error) return;
    const sc = v.score;
    $("#secTop").innerHTML = `<div class="card"><div class="row" style="gap:18px">${ring(sc / 100, sc >= 85 ? COL.good : sc >= 60 ? COL.warn : COL.bad, null, 110, 11).replace('<div class="icon"></div>', `<div class="icon"><div style="text-align:center"><div class="kpi-value">${sc}</div><div class="small muted">score</div></div></div>`)}
      <div class="grow"><div class="card-title" style="margin-bottom:8px">${icon("shield")}Security overview</div>${v.issues.length ? v.issues.map(i => `<div class="row small" style="padding:3px 0"><span class="dot ${i.level === "info" ? "" : i.level === "warn" ? "warn" : "bad"}"></span>${esc(i.text)}</div>`).join("") : `<div class="good-t">No issues found</div>`}</div></div></div>
      <div class="card"><div class="card-title" style="margin-bottom:10px">${icon("devices")}Untrusted devices online</div>${v.untrusted.length ? v.untrusted.slice(0, 6).map(d => `<div class="row small" style="padding:4px 0">${smallIcon(d.type, 15)}<span class="grow ellipsis">${esc(d.name)}</span><span class="num muted">${esc(d.ip)}</span></div>`).join("") + `<a class="small" href="#devices">Review and mark trusted →</a>` : `<div class="muted small">Every online device is marked as trusted.</div>`}</div>
      <div class="card"><div class="card-title" style="margin-bottom:10px">${icon("wifi")}Wi-Fi & login pages</div>
        ${v.wifi_ssid ? `<div class="row between small" style="padding:4px 0"><span>Network</span><b>${esc(v.wifi_ssid)}</b></div><div class="row between small" style="padding:4px 0"><span>Encryption</span><span class="pill ${/open/i.test(v.wifi_auth || "") ? "bad" : /wpa3/i.test(v.wifi_auth || "") ? "good" : "info"}">${esc(v.wifi_auth || "?")}</span></div>` : `<div class="muted small">Not on Wi-Fi</div>`}
        <div class="row between small" style="padding:4px 0"><span>Captive portal</span><span class="pill ${v.captive && v.captive.portal ? "warn" : "good"}">${v.captive ? (v.captive.portal ? "Sign-in page detected" : "None") : "Not checked"}</span></div></div>`;
    // UPnP
    const uj = v.upnp_job, u = v.upnp;
    $("#secUpnp").innerHTML = `<div class="card-head"><div class="card-title">${icon("router")}Router port forwards</div><button class="btn sm" data-run="upnp">${icon("refresh")}Check</button></div>` +
      (uj.running ? jobSpinner("Asking your router which ports it has opened…") : !u ? `<div class="muted">Lists every port your router has opened to the internet — and which device asked for it.</div>` :
        !u.found ? `<div class="callout">${icon("check")}<div>${esc(u.note)}</div></div>` :
          `<div class="small muted" style="margin-bottom:8px">${esc(u.router || "Router")}${u.external_ip ? " · " + esc(u.external_ip) : ""}${u.wan_rx ? ` · lifetime ${fmtBytes(u.wan_rx)} ↓ / ${fmtBytes(u.wan_tx)} ↑` : ""}</div>` +
          (u.mappings.length ? `<div class="table-wrap" style="max-height:260px"><table class="t"><tr><th>Port</th><th>To device</th><th>Description</th><th></th></tr>${u.mappings.map(m => `<tr><td class="num"><b>${m.external_port}</b>/${esc(m.protocol)}</td><td class="num">${esc(m.internal_client)}:${m.internal_port} <span class="muted">${esc(devLabel(m.internal_client))}</span></td><td class="ellipsis" style="max-width:180px">${esc(m.description)}</td><td>${m.risky ? '<span class="pill bad">Risky</span>' : m.service ? `<span class="pill">${esc(m.service)}</span>` : ""}</td></tr>`).join("")}</table></div>
            <div class="small muted" style="margin-top:8px">Don't recognise one? Turn off UPnP in your router, or remove the forward. Consoles and video-call apps commonly add these.</div>` : `<div class="callout">${icon("check")}<div>Your router has <b>no</b> ports forwarded to the internet.</div></div>`));
    // Exposure
    const ej = v.exposure_job, ex = v.exposure;
    $("#secExposure").innerHTML = `<div class="card-head"><div class="card-title">${icon("globe")}Visible from the internet</div><button class="btn sm" data-run="exposure">${icon("refresh")}Check</button></div>` +
      (ej.running ? jobSpinner("Looking up your public IP in internet scan data…") : !ex ? `<div class="muted">Checks what internet-wide scanners can see on your public IP (${esc(v.public_ip || "unknown")}).</div>` :
        ex.error ? `<div class="callout warn">${icon("alert")}${esc(ex.error)}</div>` :
          ex.clean ? `<div class="callout">${icon("check")}<div>Nothing on <b>${esc(ex.ip)}</b> is visible to internet scanners. 👍</div></div>` :
            `<div class="small muted" style="margin-bottom:8px">${esc(ex.ip)}${ex.hostnames.length ? " · " + esc(ex.hostnames.join(", ")) : ""}</div><div class="row wrap" style="gap:6px">${ex.ports.map(p => `<span class="pill ${p.risky ? "bad" : "warn"}">${p.port}${p.service ? " · " + esc(p.service) : ""}</span>`).join("")}</div>
            ${ex.vulns.length ? `<div class="callout warn mt">${icon("alert")}<div><b>${ex.vulns.length} known vulnerabilit${ex.vulns.length === 1 ? "y" : "ies"}</b> reported for software on these ports: ${esc(ex.vulns.slice(0, 6).join(", "))}${ex.vulns.length > 6 ? "…" : ""}. Update the device's firmware or close the port.</div></div>` : ""}
            <div class="small muted" style="margin-top:8px">Data from Shodan InternetDB, which may be a few days old.</div>`);
    // PC
    const pj = v.pc_job, pc = v.pc;
    $("#secPc").innerHTML = `<div class="card-head"><div class="card-title">${icon("pc")}This PC</div><button class="btn sm" data-run="pc">${icon("refresh")}Check</button></div>` +
      (pj.running ? jobSpinner("Reviewing firewall, antivirus and sharing settings…") : !pc || !pc.checks ? `<div class="muted">Firewall, antivirus, network profile, Remote Desktop, legacy file sharing and listening ports.</div>` :
        pc.checks.map(c => { const [cls] = statusPill(c.status); return `<div class="check"><div class="ev-ic ${cls === "good" ? "OK" : cls === "bad" ? "ALERT" : cls === "warn" ? "WARN" : "INFO"}">${icon(statusIcon(c.status))}</div><div class="grow"><b>${esc(c.title)}</b><div class="small muted">${esc(c.detail)}</div>${c.fix ? `<div class="small" style="color:var(--warn)">${esc(c.fix)}</div>` : ""}</div></div>`; }).join("") +
        (pc.listening && pc.listening.length ? `<details class="mt"><summary class="small muted" style="cursor:pointer">${pc.listening.length} listening ports</summary><div class="row wrap" style="gap:6px;margin-top:8px">${pc.listening.map(l => `<span class="pill ${l.risky ? "warn" : ""}" title="${esc(l.process)}">${l.port} · ${esc(l.service || l.process)}</span>`).join("")}</div></details>` : ""));
    // network integrity
    const dj = v.dhcp_job, dh = v.dhcp;
    $("#secNet").innerHTML = `<div class="card-head"><div class="card-title">${icon("network")}Network integrity</div><button class="btn sm" data-run="dhcp">${icon("refresh")}Check DHCP</button></div>
      <div class="check"><div class="ev-ic ${v.spoof.shared_with.length ? "ALERT" : "OK"}">${icon(v.spoof.shared_with.length ? "alert" : "check")}</div><div class="grow"><b>ARP spoofing</b><div class="small muted">${v.spoof.shared_with.length ? `Your router's address is also claimed by ${esc(v.spoof.shared_with.join(", "))} — possible interception.` : `${v.spoof.gateway_mac ? `Router ${esc(v.spoof.gateway_mac)} is unique.` : "Router not seen in the ARP table yet."} Checked every 2 minutes.`}</div></div></div>
      <div class="check"><div class="ev-ic ${dh ? (dh.rogue ? "ALERT" : dh.error ? "WARN" : "OK") : "INFO"}">${icon(dh ? (dh.rogue ? "alert" : dh.error ? "alert" : "check") : "info")}</div><div class="grow"><b>Rogue DHCP servers</b><div class="small muted">${dj.running ? "Listening for DHCP servers…" : !dh ? "Checks that only your router is handing out IP addresses." : dh.error ? esc(dh.error) : dh.rogue ? `${dh.servers.length} servers answered: ${esc(dh.servers.map(x => x.server).join(", "))}. Only your router should.` : dh.servers.length ? `Only ${esc(dh.servers[0].server)} answered — good.` : "No DHCP server answered."}</div></div></div>`;
    // VPN
    const lj = v.leak, lk = lj.result;
    const vpnUp = v.vpn.filter(a => a.up);
    $("#secVpn").innerHTML = `<div class="card-head"><div class="card-title">${icon("vpn")}VPN & leak test</div><button class="btn sm" data-run="leak">${icon("play")}Run leak test</button></div>
      <div class="row between" style="padding:6px 0"><span>VPN status</span><span class="pill ${vpnUp.length ? "good" : ""}">${vpnUp.length ? "Connected · " + esc(vpnUp.map(a => a.name).join(", ")) : v.vpn.length ? "Disconnected" : "No VPN adapter found"}</span></div>
      ${lj.running ? jobSpinner("Checking where your traffic and DNS lookups exit…") : lk ? `<div class="kv mt" style="grid-template-columns:150px 1fr"><div class="k">Traffic exits as</div><div class="v">${esc(lk.public_ip || "?")} · ${esc(lk.public_isp || "")}${lk.public_city ? " · " + esc(lk.public_city) : ""}</div>
        <div class="k">DNS resolver</div><div class="v">${esc(lk.resolver_ip || "?")}${lk.resolver_isp ? " · " + esc(lk.resolver_isp) : ""}</div></div>
        <div class="small muted" style="margin-top:8px">${lk.vpn.length ? "With a VPN on, both should belong to your VPN provider — if either shows your home ISP, you have a leak." : "Connect your VPN and run the test again to check for leaks."}</div>` : `<div class="muted small mt">Alerts automatically if your VPN drops. The leak test checks your real IP and DNS aren't escaping the tunnel.</div>`}`;
    // capture
    const cap = v.capture;
    $("#secCap").innerHTML = `<div class="card-head"><div class="card-title">${icon("record")}Traffic capture</div></div>
      <div class="muted small" style="margin-bottom:12px">Records network traffic to a .pcapng file you can open in Wireshark — useful evidence for your ISP or IT support. Uses Windows' built-in pktmon${v.admin ? "" : " and needs administrator rights"}.</div>
      ${cap.running ? `<div class="progress"><span style="width:${100 * cap.elapsed / cap.seconds}%"></span></div><div class="row between mt"><span class="small">Recording… ${Math.round(cap.elapsed)} / ${cap.seconds} s</span><button class="btn sm danger" id="capStop">${icon("stop")}Stop</button></div>` :
        `<div class="row" style="gap:8px">${[30, 60, 300].map(sv => `<button class="btn sm" data-cap="${sv}" ${v.windows ? "" : "disabled"}>${icon("record")}${sv < 60 ? sv + " s" : sv / 60 + " min"}</button>`).join("")}</div>
        ${cap.error ? `<div class="callout warn mt">${icon("alert")}${esc(cap.error)}</div>` : ""}${cap.file ? `<div class="callout mt">${icon("check")}<div>Saved ${fmtBytes(cap.size)}: <span class="num small">${esc(cap.file)}</span><div style="margin-top:6px"><button class="btn sm" id="capShow">${icon("folder")}Show file</button></div></div></div>` : ""}`}`;
    $$("[data-run]").forEach(b => b.onclick = async () => { await API.run_security(b.dataset.run); this.refresh(); });
    $$("[data-cap]").forEach(b => b.onclick = async () => { const r = await API.capture_start(+b.dataset.cap); if (!r.started) toast((r.state && r.state.error) || r.error || "Couldn't start", "bad"); this.refresh(); });
    if ($("#capStop")) $("#capStop").onclick = () => API.capture_stop();
    if ($("#capShow")) $("#capShow").onclick = () => API.reveal_file(cap.file);
  },
};
function devLabel(ip) {
  const d = (PAGES.devices.data && PAGES.devices.data.devices || []).find(x => x.ip === ip);
  return d ? devName(d) : "";
}

// ============================================================ Troubleshooter
PAGES.doctor = {
  shell() { return head("Troubleshooter", "Step-by-step check from this PC out to the internet, with one-click fixes") +
    `<div class="card doc-hero"><div><div class="hero-title">Something not right?</div><div class="muted" style="margin-top:4px">NetWatch checks your adapter, Wi-Fi, router, internet, DNS and web access in order, and tells you exactly where it breaks.</div></div><button class="go-btn" id="docGo" style="width:96px;height:96px;font-size:15px">CHECK</button></div>
    <div class="card mt" id="docSteps"><div class="empty">${icon("doctor")}<div>Press <b>Check</b> to start.</div></div></div>`; },
  init() {
    $("#docGo").onclick = async () => { await API.run_troubleshoot(); this.watch(); };
    API.get_troubleshoot().then(j => { if (j.running) this.watch(); else if (j.result) this.show(j); });
  },
  watch() {
    $("#docSteps").innerHTML = jobSpinner("Running checks… this takes about 15 seconds.");
    $("#docGo").disabled = true;
    pollJob(() => API.get_troubleshoot(), j => { $("#docGo").disabled = false; this.show(j); });
  },
  show(j) {
    if (j.error) { $("#docSteps").innerHTML = `<div class="callout warn">${icon("alert")}${esc(j.error)}</div>`; return; }
    const steps = j.result || [];
    const first = steps.find(s => s.status === "fail") || steps.find(s => s.status === "warn");
    const summary = !first ? `<div class="callout" style="margin-bottom:14px">${icon("check")}<div><b>Everything checks out.</b> If something still feels slow, try a speed test or look at the History page for patterns.</div></div>` :
      `<div class="callout ${first.status === "fail" ? "warn" : ""}" style="margin-bottom:14px">${icon(first.status === "fail" ? "alert" : "info")}<div><b>${first.status === "fail" ? "Found the problem" : "Worth a look"}: ${esc(first.title)}</b><br>${esc(first.detail)}</div></div>`;
    $("#docSteps").innerHTML = summary + `<div class="steps">${steps.map((s, i) => { const [cls, label] = statusPill(s.status); return `<div class="step ${cls}"><div class="step-n">${icon(statusIcon(s.status))}</div><div class="grow"><div class="row between"><b>${esc(s.title)}</b><span class="pill ${cls}">${label}</span></div><div class="muted small" style="margin-top:3px">${esc(s.detail)}</div>
      ${s.fixes.length ? `<div class="row wrap" style="gap:6px;margin-top:8px">${s.fixes.map(f => `<button class="btn sm" data-fix="${f}">${icon("wrench")}${esc(j.fixes[f].title)}${j.fixes[f].admin && !j.admin ? " (admin)" : ""}</button>`).join("")}</div>` : ""}</div></div>`; }).join("")}</div>
      <div class="small muted" style="margin-top:14px">Last run ${fmtAgo(j.finished)}</div>`;
    $$("[data-fix]").forEach(b => b.onclick = async () => { b.disabled = true; const r = await API.run_fix(b.dataset.fix); b.disabled = false; r.error ? toast(r.error, "bad") : toast("Done — run the check again to confirm", "good"); });
  },
};

// ============================================================ More tests (tools)
PAGES.tools = {
  shell() { return head("More tests", "Deeper checks for specific problems") + `<div class="grid g-2">
    <div class="card" id="tM365"></div><div class="card" id="tJust"></div></div><div class="grid g-2 mt"><div class="card" id="tCloud"></div><div class="card" id="tV6"></div></div>`; },
  init() {
    const block = (id, kind, title, ic, desc, btn, render, input) => {
      const el = $("#" + id);
      const draw = j => {
        el.innerHTML = `<div class="card-head"><div class="card-title">${icon(ic)}${title}</div><button class="btn sm primary" data-k="${kind}" ${j && j.running ? "disabled" : ""}>${icon("play")}${btn}</button></div>${input || ""}` +
          (j && j.running ? jobSpinner("Testing…") : j && j.error ? `<div class="callout warn">${icon("alert")}${esc(j.error)}</div>` : j && j.result ? render(j.result) : `<div class="muted">${desc}</div>`);
        $(`[data-k=${kind}]`, el).onclick = async () => { const arg = $("input", el) ? $("input", el).value : null; await API.run_tool(kind, arg); draw({ running: true }); pollJob(() => API.get_tool(kind), draw); };
      };
      API.get_tool(kind).then(j => { draw(j); if (j && j.running) pollJob(() => API.get_tool(kind), draw); });
    };
    const gc = g => ({ Excellent: "good", Good: "good", Fair: "warn", Poor: "bad" }[g] || "");
    block("tM365", "m365", "Microsoft 365 connectivity", "sites", "Times DNS, connection and TLS set-up to Outlook, Teams, SharePoint and sign-in, and checks for proxies that slow Microsoft 365 down.", "Test", r =>
      `<div class="table-wrap"><table class="t"><tr><th>Service</th><th>DNS</th><th>Connect</th><th>TLS</th><th></th></tr>${r.endpoints.map(e => e.error ? `<tr><td>${esc(e.name)}</td><td colspan="4" class="bad-t">${esc(e.error)}</td></tr>` : `<tr><td><b>${esc(e.name)}</b><div class="small muted ellipsis" style="max-width:220px">${esc(e.cname || e.host)}</div></td><td class="num">${fmtMs(e.dns_ms)} ms</td><td class="num">${fmtMs(e.tcp_ms)} ms</td><td class="num">${fmtMs(e.tls_ms)} ms</td><td><span class="pill ${gc(e.grade)}">${e.grade || "—"}</span></td></tr>`).join("")}</table></div>
      <div class="kv mt" style="grid-template-columns:130px 1fr"><div class="k">Proxy (WinHTTP)</div><div class="v">${esc(r.proxy.winhttp)}${r.proxy.user ? " · browser proxy ON" : ""}</div><div class="k">DNS resolver exit</div><div class="v num">${esc(r.resolver_egress || "?")}</div></div>
      ${r.notes.map(n => `<div class="callout mt">${icon("info")}<div>${esc(n)}</div></div>`).join("")}`);
    block("tJust", "justme", "Is it just me?", "globe", "Checks a dozen popular sites at once to tell whether a problem is your connection or the website.", "Check",
      r => `<div class="callout" style="margin:10px 0">${icon("info")}<div>${esc(r.verdict)}</div></div><div class="tiles">${r.sites.map(x => `<div class="tile" style="--c:${x.ok ? COL.good : COL.bad};padding:10px 12px"><div class="row between"><b class="ellipsis small">${esc(x.name)}</b>${smallIcon(x.ok ? "check" : "x", 14)}</div><div class="small muted">${x.ok ? (x.ms != null ? x.ms + " ms" : "OK") : esc(x.detail)}</div></div>`).join("")}</div>
      ${STATE && STATE.public && STATE.public.isp ? `<div class="small muted mt">Suspect your ISP? <a href="#" onclick="API.open_url('https://downdetector.co.uk/search/?q=${encodeURIComponent(STATE.public.isp)}');return false">Check Downdetector for ${esc(STATE.public.isp)}</a></div>` : ""}`,
      `<input class="input" placeholder="Optional: a specific site, e.g. bbc.co.uk" style="margin-bottom:6px">`);
    block("tCloud", "cloud", "Cloud & game server latency", "cloud", "Connection times to cloud regions around the world. Add your own game servers or work systems in Settings → Monitoring.", "Measure", r => {
      const max = Math.max(50, ...r.filter(x => x.ms).map(x => x.ms));
      return `<div class="bars-h">${r.map(x => `<div class="b" style="grid-template-columns:150px 1fr 70px"><span class="ellipsis small">${esc(x.name)}${x.custom ? ' <span class="pill" style="font-size:10px">custom</span>' : ""}</span><div class="track"><span style="width:${x.ms ? Math.max(2, 100 * x.ms / max) : 0}%;background:${x.ms == null ? COL.bad : x.ms < 40 ? COL.good : x.ms < 120 ? COL.cyan : COL.warn}"></span></div><span class="num small" style="text-align:right">${x.ms == null ? "no reply" : x.ms + " ms"}</span></div>`).join("")}</div>`;
    });
    block("tV6", "ipv6", "IPv6 health", "globe", "Checks whether IPv6 is working properly. A half-working IPv6 setup is a classic cause of slow page loads.", "Check", r =>
      `<div class="callout ${r.status === "broken" ? "warn" : ""}" style="margin:10px 0">${icon(r.status === "broken" ? "alert" : "check")}<div>${esc(r.detail)}</div></div>
      <div class="kv" style="grid-template-columns:120px 1fr"><div class="k">IPv4 connect</div><div class="v num">${fmtMs(r.v4_ms)} ms</div><div class="k">IPv6 connect</div><div class="v num">${r.v6_ms != null ? fmtMs(r.v6_ms) + " ms" : "—"}</div>${r.addresses.length ? `<div class="k">Addresses</div><div class="v num small">${r.addresses.map(a => esc(a.address)).join("<br>")}</div>` : ""}</div>`);
  },
};

// ============================================================ Ask NetWatch
PAGES.ask = {
  history: [],
  shell() {
    const sugg = ["Why was my internet slow last night?", "Is my broadband giving me what I pay for?", "Which device uses the network most at night?", "Summarise this week's outages for my ISP", "How can I improve my Wi-Fi?", "Is anything on my network a security risk?"];
    return head("Ask NetWatch", "Ask questions about your network in plain English") + `<div class="card chat"><div id="chatLog" class="chat-log"></div>
      <div class="row wrap" id="chatSugg" style="gap:6px;margin:10px 0">${sugg.map(q => `<button class="btn sm ghost sugg">${esc(q)}</button>`).join("")}</div>
      <div class="row" style="gap:8px"><input class="input" id="chatIn" placeholder="Ask about your connection, devices, Wi-Fi, outages…"><button class="btn primary" id="chatSend">${icon("sparkle")}Ask</button></div>
      <div class="small muted" style="margin-top:8px">Powered by Claude. Your monitoring summary is sent to Anthropic's API with each question. Add your API key in Settings → Integrations.</div></div>`;
  },
  init() {
    this.draw();
    const send = async q => {
      q = (q || $("#chatIn").value).trim(); if (!q) return;
      $("#chatIn").value = ""; this.history.push({ role: "user", content: q }); this.draw(true);
      const r = await API.ask(q, this.history.slice(0, -1));
      this.history.push({ role: "assistant", content: r.error ? `⚠️ ${r.error}` : r.answer, error: !!r.error }); this.draw();
    };
    $("#chatSend").onclick = () => send(); $("#chatIn").onkeydown = e => { if (e.key === "Enter") send(); };
    $$(".sugg").forEach(b => b.onclick = () => send(b.textContent));
  },
  draw(thinking) {
    const md = t => esc(t).replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/^[-•] (.*)$/gm, "• $1").replace(/\n/g, "<br>");
    $("#chatLog").innerHTML = (this.history.length ? "" : `<div class="empty">${icon("chat")}<div>Ask anything about your network. NetWatch shares its latest measurements, history and device list with the assistant.</div></div>`) +
      this.history.map(m => `<div class="bubble ${m.role}${m.error ? " err" : ""}">${md(m.content)}</div>`).join("") + (thinking ? `<div class="bubble assistant">${icon("refresh", "spin").replace("<svg", '<svg style="width:14px;height:14px;vertical-align:-2px"')} Thinking…</div>` : "");
    $("#chatLog").scrollTop = 1e9;
  },
};

// ============================================================ Sites
PAGES.sites = {
  interval: 10000,
  shell() { return head("Sites", "Watch several locations from one dashboard") + `<div id="sitesBody"></div>`; },
  async refresh() {
    const v = await API.get_sites(); if (!v || v.error) return;
    const card = (x, local) => {
      const st = x.status || {}, up = x.internet_up;
      return `<div class="card site ${x.stale ? "offline" : ""}"><div class="row"><span class="dot ${x.stale ? "" : st.level || ""} live"></span><div class="grow"><div class="dev-name">${esc(x.name)} ${local ? '<span class="pill info">This PC</span>' : ""}</div><div class="dev-meta">${esc((x.public || {}).isp || "")} · ${x.stale ? "last report " + fmtAgo(x.last_seen) : esc(st.title || "")}</div></div>
        ${!local && v.role === "hub" ? `<button class="btn ghost sm" data-del="${esc(x.name)}">${smallIcon("trash", 14)}</button>` : ""}</div>
        <div class="grid g-4" style="gap:8px;margin-top:14px">${[["Latency", fmtMs(x.latency) + " ms"], ["Loss", isNum(x.loss) ? x.loss.toFixed(1) + "%" : "—"], ["Uptime", isNum(x.uptime) ? x.uptime.toFixed(2) + "%" : "—"], ["Devices", (x.devices || {}).online ?? "—"]].map(([k, val]) => `<div><div class="small muted">${k}</div><b class="num">${val}</b></div>`).join("")}</div>
        <div class="small muted" style="margin-top:10px">Speed ${x.speed && x.speed.down ? `${fmtMbps(x.speed.down)} / ${fmtMbps(x.speed.up)} Mbps` : "not tested"} · ${up === false ? '<span class="bad-t">internet down</span>' : "online"}</div></div>`;
    };
    const guide = v.role === "standalone" ? `<div class="callout" style="margin-bottom:16px">${icon("info")}<div><b>Monitor more than one place.</b> Pick one PC as the <b>hub</b> and set the others as <b>agents</b> in Settings → Integrations → Multi-site, using the same site key. Agents report every minute; the hub shows them all here and alerts if a site goes offline.</div></div>` :
      v.role === "agent" ? `<div class="callout" style="margin-bottom:16px">${icon(v.push.error ? "alert" : "check")}<div>This PC reports to your hub${v.push.last_push ? `, last sent ${fmtAgo(v.push.last_push)}` : ""}.${v.push.error ? " Error: " + esc(v.push.error) : ""}</div></div>` : "";
    $("#sitesBody").innerHTML = guide + `<div class="grid g-3">${card(v.self, true)}${v.sites.map(x => card(x)).join("")}</div>` + (v.role === "hub" && !v.sites.length ? `<div class="muted mt">No agents have reported yet.</div>` : "");
    $$("[data-del]").forEach(b => b.onclick = async () => { await API.delete_site(b.dataset.del); this.refresh(); });
  },
};

// ============================================================ Apps (tabs)
const APPS_TRAFFIC = PAGES.apps;
PAGES.apps = {
  tab: "traffic", interval: 2000,
  shell() {
    return head("Apps & traffic", "Which programs use the network, who they talk to, and where", `<div class="seg" id="appTabs">${[["traffic", "apps", "Traffic"], ["domains", "list", "Sites contacted"], ["world", "globe", "World map"], ["security", "shield", "App security"]].map(([t, ic, l]) => `<button data-t="${t}" class="${this.tab === t ? "on" : ""}">${icon(ic)}${l}</button>`).join("")}</div>`) + `<div id="appBody"></div>`;
  },
  init() { $$("#appTabs button").forEach(b => b.onclick = () => { this.tab = b.dataset.t; go("apps"); }); this.mount(); },
  mount() {
    const body = $("#appBody");
    if (this.tab === "traffic") {
      const tmp = document.createElement("div"); tmp.innerHTML = APPS_TRAFFIC.shell(); tmp.querySelector(".page-head").remove();
      body.innerHTML = tmp.innerHTML; APPS_TRAFFIC.init(); this.interval = 2000;
    } else { body.innerHTML = `<div class="empty">Loading…</div>`; this.interval = this.tab === "world" ? 15000 : 8000; }
  },
  async refresh() {
    if (this.tab === "traffic") return APPS_TRAFFIC.refresh();
    if (this.tab === "world") return this.world();
    const a = await API.get_apps_security(); if (!a || a.error) return;
    if (this.tab === "domains") this.domains(a); else this.appsec(a);
  },
  domains(a) {
    const apps = Object.entries(a.domains).sort((x, y) => y[1].length - x[1].length);
    const trackers = Object.entries(a.trackers).sort((x, y) => y[1] - x[1]);
    $("#appBody").innerHTML = (!a.dns_cache_supported ? `<div class="callout warn">${icon("alert")}Windows only.</div>` : "") +
      `<div class="grid g-3"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("list")}Websites each app talks to</div><span class="card-sub">from Windows' DNS cache</span></div>
      ${apps.length ? apps.slice(0, 25).map(([app, ds]) => `<details class="app-dom"><summary><div class="avatar" style="background:${avatarColor(app)};width:26px;height:26px;font-size:12px">${esc(app[0] || "?").toUpperCase()}</div><b>${esc(app.replace(/\.exe$/i, ""))}</b><span class="muted small">${plural(ds.length, "site")}${ds.some(d => d.tracker) ? ` · <span class="warn-t">${ds.filter(d => d.tracker).length} tracker${ds.filter(d => d.tracker).length > 1 ? "s" : ""}</span>` : ""}</span></summary>
        <div class="row wrap" style="gap:6px;padding:8px 0 4px 36px">${ds.map(d => `<span class="pill ${d.tracker ? "warn" : ""}" title="seen ${d.count}× · last ${fmtAgo(d.last)}">${d.tracker ? smallIcon("eye", 12) + " " : ""}${esc(d.domain)}</span>`).join("")}</div></details>`).join("") : `<div class="empty">Collecting… sites appear as apps connect (checked every 30 seconds).</div>`}</div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("eye")}Trackers & ads</div></div>${trackers.length ? `<div class="bars-h">${trackers.slice(0, 10).map(([app, n]) => `<div class="b" style="grid-template-columns:1fr 80px 50px"><span class="ellipsis small">${esc(app.replace(/\.exe$/i, ""))}</span><div class="track"><span style="width:${100 * n / trackers[0][1]}%;background:${COL.warn}"></span></div><span class="num small" style="text-align:right">${n}</span></div>`).join("")}</div><div class="small muted mt">Connections to known advertising, analytics and telemetry domains.</div>` : `<div class="muted small">No tracker connections seen yet.</div>`}</div></div>`;
  },
  appsec(a) {
    const rows = a.apps.map(x => `<tr><td><div class="row"><div class="avatar" style="background:${avatarColor(x.name)};width:26px;height:26px;font-size:12px">${esc(x.name[0] || "?").toUpperCase()}</div><div><b>${esc(x.name)}</b><div class="small muted ellipsis" style="max-width:380px">${esc(x.path)}</div></div></div></td>
      <td>${x.signed === "signed" ? `<span class="pill good">Signed</span>` : x.signed === "unsigned" ? `<span class="pill warn">Unsigned</span>` : `<span class="pill">${esc(x.signed || "Checking…")}</span>`}</td><td class="small">${esc(x.publisher || "")}</td><td class="muted">${fmtAgo(x.first_seen)}</td>
      <td>${x.blocked ? `<button class="btn sm" data-unblock="${esc(x.path)}">${icon("unlock")}Unblock</button>` : `<button class="btn sm danger" data-block="${esc(x.path)}">${icon("lock")}Block</button>`}</td></tr>`).join("");
    $("#appBody").innerHTML = (!a.admin ? `<div class="callout warn" style="margin-bottom:14px">${icon("shield")}<div>Blocking apps creates Windows Firewall rules, which needs administrator rights. Use <b>Restart as administrator</b> on the Traffic tab.</div></div>` : "") +
      `<div class="card"><div class="card-head"><div class="card-title">${icon("shield")}Apps that have used the internet</div><span class="card-sub">NetWatch alerts the first time a new app connects</span></div>
      <div class="table-wrap" style="max-height:620px"><table class="t"><tr><th>App</th><th>Signature</th><th>Publisher</th><th>First seen</th><th></th></tr>${rows || '<tr><td colspan="5" class="muted">Building the list…</td></tr>'}</table></div></div>`;
    $$("[data-block]").forEach(b => b.onclick = async () => { const r = await API.block_app(b.dataset.block, true); r.error ? toast(r.error, "bad") : toast("Blocked — the app can no longer reach the internet", "good"); this.refresh(); });
    $$("[data-unblock]").forEach(b => b.onclick = async () => { const r = await API.block_app(b.dataset.unblock, false); r.error ? toast(r.error, "bad") : toast("Unblocked", "good"); this.refresh(); });
  },
  async world() {
    const w = await API.get_world(); if (!w || w.error) return;
    const body = $("#appBody");
    if (!w.enabled) {
      body.innerHTML = `<div class="card empty">${icon("globe")}<div style="max-width:520px;margin:0 auto"><b>See where your apps connect on a world map.</b><br>To place IP addresses on the map, NetWatch looks them up with the free ip-api.com service — so those addresses are shared with it. Turn it on if you're happy with that.</div><button class="btn primary mt" id="geoOn">${icon("globe")}Turn on world map</button></div>`;
      $("#geoOn").onclick = async () => { const s = await API.get_settings(); s.geo_enabled = true; await API.save_settings(s); toast("World map on — locations appear within a minute", "good"); this.world(); };
      return;
    }
    const W = window.WORLD_W, H = window.WORLD_H, px = lon => (lon + 180) / 360 * W, py = lat => (90 - lat) / 180 * H;
    const max = Math.max(1, ...w.points.map(p => p.count));
    const me = STATE && STATE.extra ? null : null;
    const dots = w.points.map(p => { const r = 3 + 9 * Math.sqrt(p.count / max); const foreign = w.home && p.country && p.country !== w.home && !/United Kingdom|Ireland|Netherlands|Germany|France|Belgium|United States/.test(p.country);
      return `<circle cx="${px(p.lon)}" cy="${py(p.lat)}" r="${r}" fill="${foreign ? COL.warn : COL.cyan}" fill-opacity=".75" stroke="${foreign ? COL.warn : COL.cyan}" stroke-width="1.5"><title>${esc(p.city || "")}${p.city ? ", " : ""}${esc(p.country || "")} — ${p.count} address${p.count > 1 ? "es" : ""}\n${esc(p.org || "")}\n${esc(p.apps.join(", "))}</title></circle>`; }).join("");
    body.innerHTML = `<div class="grid g-3"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("globe")}Where this PC connects</div><span class="card-sub">${w.points.length} locations${w.pending ? ` · ${w.pending} still to look up` : ""}</span></div>
      <svg viewBox="0 20 ${W} ${H - 70}" class="world"><path d="${window.WORLD_PATH}" fill="rgba(148,163,184,.16)" stroke="rgba(148,163,184,.35)" stroke-width=".6"/>${dots}</svg>
      <div class="legend mt"><span><i style="background:${COL.cyan}"></i>Common locations</span><span><i style="background:${COL.warn}"></i>Less usual countries — worth a glance</span></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("list")}Countries</div></div>${w.countries.slice(0, 14).map(([c, n]) => `<div class="row between small" style="padding:5px 0;border-bottom:1px solid var(--border)"><span>${esc(c)}</span><b class="num">${n}</b></div>`).join("") || '<div class="muted small">Looking up locations…</div>'}</div></div>`;
  },
};

// ============================================================ Settings (v3)
PAGES.settings = {
  tab: "general",
  shell() {
    const tabs = [["general", "General"], ["monitoring", "Monitoring"], ["alerts", "Alerts"], ["integrations", "Integrations"], ["phone", "Phone & sites"], ["data", "Data & updates"]];
    return head("Settings", "Tune monitoring, alerts and integrations", `<button class="btn primary" id="saveSet">${icon("check")}Save changes</button>`) +
      `<div class="seg" id="setTabs" style="margin-bottom:16px">${tabs.map(([t, l]) => `<button data-t="${t}" class="${this.tab === t ? "on" : ""}">${l}</button>`).join("")}</div><div id="setBody"><div class="empty">Loading…</div></div>`;
  },
  async init() {
    $$("#setTabs button").forEach(b => b.onclick = () => { this.collectInto(); this.tab = b.dataset.t; $$("#setTabs button").forEach(x => x.classList.toggle("on", x === b)); this.render(); });
    $("#saveSet").onclick = () => this.save();
    this.s = await API.get_settings();
    if (!this.s || this.s.error) { $("#setBody").innerHTML = `<div class="callout warn">${icon("alert")}Couldn't load settings: ${esc(this.s && this.s.error)}</div>`; return; }
    this.render();
  },
  render() {
    const s = this.s, r = s.remote, m = s._meta;
    const row = (t, d, c) => `<div class="settings-row"><div class="l"><div class="t">${t}</div><div class="d">${d}</div></div><div class="c">${c}</div></div>`;
    const sw = (k, on) => `<label class="switch"><input type="checkbox" data-k="${k}" ${on ? "checked" : ""}><span></span></label>`;
    const num = (k, v, w = 110, a = "") => `<input class="input num" type="number" data-k="${k}" value="${v ?? ""}" style="width:${w}px" ${a}>`;
    const txt = (k, v, ph = "", type = "text", w = "") => `<input class="input" type="${type}" data-k="${k}" value="${esc(v ?? "")}" placeholder="${esc(ph)}" ${w ? `style="width:${w}"` : ""}>`;
    const sel = (k, v, opts) => `<select class="input" data-k="${k}" style="width:220px">${opts.map(([o, l]) => `<option value="${o}" ${String(v) === o ? "selected" : ""}>${l}</option>`).join("")}</select>`;
    const card = (ic, title, inner, extra = "") => `<div class="card"><div class="card-head"><div class="card-title">${icon(ic)}${title}</div>${extra}</div>${inner}</div>`;
    let html = "";
    if (this.tab === "general") html = `<div class="grid g-2">` + card("settings", "Appearance & startup",
      row("Theme", "Dark or light appearance", sel("theme", s.theme, [["dark", "Dark"], ["light", "Light"]])) +
      row("Start with Windows", m.windows ? "Launch quietly into the system tray when you sign in" : "Windows only", sw("start_with_windows", s.start_with_windows)) +
      row("Keep running in the tray", "Closing the window hides NetWatch instead of quitting", sw("minimize_to_tray", s.minimize_to_tray)) +
      row("Mini overlay at start-up", "Small always-on-top ping & speed widget", sw("overlay_on_start", s.overlay_on_start)) +
      row("Mini overlay now", "Show or hide it (also in the tray menu)", `<button class="btn" id="ovl">${icon("eye")}Toggle overlay</button>`)) +
      card("speed", "Your broadband plan",
        row("Download speed", "Advertised download (Mbps)", num("plan_down_mbps", s.plan_down_mbps || "")) +
        row("Upload speed", "Advertised upload (Mbps)", num("plan_up_mbps", s.plan_up_mbps || "")) +
        row("Monthly data allowance", "GB per billing cycle (0 = unlimited)", num("data_cap_gb", s.data_cap_gb)) +
        row("Billing cycle starts", "Day of the month", num("billing_day", s.billing_day, 90, 'min="1" max="28"')) +
        row("Cost of downtime", "£ per hour offline, for reports (0 = off)", num("downtime_cost_per_hour", s.downtime_cost_per_hour))) + `</div>`;
    if (this.tab === "monitoring") html = `<div class="grid g-2">` + card("clock", "Connection",
      row("Ping targets", "Servers used to judge whether the internet is up", txt("targets", s.targets.join(", "))) +
      row("Ping interval", "Seconds between checks", num("ping_interval", s.ping_interval, 90, 'min="1"')) +
      row("High latency alert", "Warn above (ms)", num("latency_threshold_ms", s.latency_threshold_ms)) +
      row("Packet loss alert", "Warn above (%)", num("loss_threshold_pct", s.loss_threshold_pct)) +
      row("Smart anomaly alerts", "Learn what's normal for each hour and flag unusual behaviour", sw("anomaly_alerts", s.anomaly_alerts)) +
      row("Extra DNS servers", "Public resolvers to compare against", txt("dns_extra", (s.dns_extra || []).join(", ")))) +
      card("devices", "Devices, Wi-Fi & tests",
        row("Device scan", "Minutes between full scans (0 = off)", num("auto_scan_minutes", s.auto_scan_minutes)) +
        row("Weak Wi-Fi alert", "Warn below this signal % (0 = off)", num("wifi_signal_alert", s.wifi_signal_alert)) +
        row("Automatic speed tests", "Hours between tests (0 = off) · ~200–500 MB each", num("speedtest_interval_hours", s.speedtest_interval_hours)) +
        row("Slow speed alert", "Warn below this % of your plan", num("speed_alert_pct", s.speed_alert_pct)) +
        row("Custom latency targets", "host:port, comma separated — game servers, work VPN…", txt("cloud_custom", (s.cloud_custom || []).join(", "), "e.g. vpn.company.com:443")) +
        row("World map lookups", "Send connection IPs to ip-api.com to place them on a map", sw("geo_enabled", s.geo_enabled))) + `</div>`;
    if (this.tab === "alerts") html = `<div class="grid g-2">` + card("events", "On this PC",
      row("Desktop notifications", "Pop-ups for outages and problems", sw("notify", s.notify)) +
      row("New device alerts", "When an unknown device joins your network", sw("notify_new_devices", s.notify_new_devices)) +
      row("New app alerts", "When a program uses the internet for the first time", sw("new_app_alerts", s.new_app_alerts)) +
      row("Quiet hours", "Only internet outages and security alerts pop up", sw("quiet_enabled", s.quiet_enabled)) +
      row("Quiet from / until", "24-hour times", `${txt("quiet_start", s.quiet_start, "22:30", "time", "120px")} ${txt("quiet_end", s.quiet_end, "07:00", "time", "120px")}`) +
      row("Weekly summary", "Every Monday morning via your remote channels below", sw("weekly_summary", s.weekly_summary) + `<button class="btn sm" id="weeklyNow">Send now</button>`)) +
      card("bolt", "Remote alerts", row("What to send", "Minimum level for email / Teams / phone", sel("remote.min_level", r.min_level, [["ALERT", "Alerts only"], ["WARN", "Alerts & warnings"], ["OK", "Everything incl. recoveries"]])) +
        `<div class="section-title">Email</div>` + row("Enabled", "", sw("remote.email_enabled", r.email_enabled)) + row("SMTP server", "e.g. smtp.office365.com", txt("remote.smtp_host", r.smtp_host)) +
        row("Port / username", "", `${num("remote.smtp_port", r.smtp_port, 80)} ${txt("remote.smtp_user", r.smtp_user, "", "text", "200px")}`) + row("Password", "Encrypted with your Windows account", txt("remote.smtp_password", r.smtp_password, "", "password")) + row("Send to", "", txt("remote.email_to", r.email_to)) +
        `<div class="section-title">Microsoft Teams</div>` + row("Enabled", "Channel ⋯ → Workflows → “Post to a channel when a webhook request is received”", sw("remote.teams_enabled", r.teams_enabled)) + row("Webhook URL", "", txt("remote.teams_webhook", r.teams_webhook)) +
        `<div class="section-title">Phone push (ntfy app)</div>` + row("Enabled", "Subscribe to the same topic in the free ntfy app", sw("remote.ntfy_enabled", r.ntfy_enabled)) + row("Topic / server", "Pick something hard to guess", `${txt("remote.ntfy_topic", r.ntfy_topic, "netwatch-xxxx", "text", "150px")} ${txt("remote.ntfy_server", r.ntfy_server, "", "text", "140px")}`),
        `<button class="btn sm" id="testRemote">${icon("play")}Send test</button>`) + `</div>`;
    if (this.tab === "integrations") html = `<div class="grid g-2">` +
      card("router", "Router (TP-Link)", row("Enabled", m.router && m.router.error ? `<span class="bad-t">${esc(m.router.error)}</span>` : m.router && m.router.last_ok ? `<span class="good-t">Connected · last read ${fmtAgo(m.router.last_ok)}</span>` : "Read status, ports, Wi-Fi and connected devices straight from your router", sw("router_enabled", s.router_enabled)) +
        row("Router address", "Leave blank to use your default gateway", txt("router_host", s.router_host, "e.g. 192.168.0.1")) +
        row("Username / password", "The router's admin login — the password is stored encrypted. Some ISP routers want 'user' rather than 'admin'.", `${txt("router_user", s.router_user, "admin", "text", "110px")} ${txt("router_password", s.router_password, "", "password", "170px")}`) +
        row("Check every", "Seconds (minimum 60). The router allows one admin at a time, so NetWatch signs in, reads and signs out.", num("router_interval", s.router_interval, 100, 'min="60"')) +
        `<div class="small muted">Read-only: NetWatch never changes router settings. After 3 failed sign-ins it stops trying, so it can't lock your account.</div>`,
        `<button class="btn sm" id="routerTest">${icon("play")}Test</button>`) +
      card("sparkle", "Ask NetWatch (AI assistant)", row("Anthropic API key", "From console.anthropic.com — stored encrypted", txt("ai_key", s.ai_key, "sk-ant-…", "password")) + row("Model", "Claude model to use", txt("ai_model", s.ai_model))) +
      card("network", "Home Assistant (MQTT)", row("Enabled", m.mqtt.connected ? `<span class="good-t">Connected</span>` : m.mqtt.error ? `<span class="bad-t">${esc(m.mqtt.error)}</span>` : "Publishes sensors with auto-discovery", sw("mqtt_enabled", s.mqtt_enabled)) +
        row("Broker", "Host and port", `${txt("mqtt_host", s.mqtt_host, "homeassistant.local", "text", "180px")} ${num("mqtt_port", s.mqtt_port, 90)}`) + row("Username / password", "", `${txt("mqtt_user", s.mqtt_user, "", "text", "140px")} ${txt("mqtt_password", s.mqtt_password, "", "password", "140px")}`) +
        row("Discovery prefix", "Usually 'homeassistant'", txt("mqtt_discovery_prefix", s.mqtt_discovery_prefix)) + row("Device presence", "Publish named devices as presence sensors", sw("mqtt_publish_devices", s.mqtt_publish_devices))) +
      card("shield", "Pi-hole / AdGuard Home", row("Type", "", sel("dnsfilter_type", s.dnsfilter_type, [["pihole", "Pi-hole"], ["adguard", "AdGuard Home"]])) + row("Address", "e.g. http://pi.hole or http://192.168.1.10", txt("dnsfilter_url", s.dnsfilter_url)) +
        row("Username", "AdGuard only", txt("dnsfilter_user", s.dnsfilter_user)) + row("Password / API token", "Pi-hole v6 password or v5 API token", txt("dnsfilter_password", s.dnsfilter_password, "", "password"))) +
      card("printer", "Printers & NAS (SNMP)", row("Community name", "Read-only community, usually 'public'", txt("snmp_community", s.snmp_community)) + `<div class="small muted">Open a printer or NAS on the Devices page and press <b>Read health</b> to see toner, disks and storage.</div>`) + `</div>`;
    if (this.tab === "phone") html = `<div class="grid g-2">` +
      card("phone2", "Phone dashboard", row("Enabled", "View NetWatch from a phone on your home network", sw("lan_enabled", s.lan_enabled)) + row("PIN", "Needed to open the dashboard (4+ digits)", txt("lan_pin", s.lan_pin, "", "password", "160px")) + row("Port", "", num("lan_port", s.lan_port)) +
        (m.lan.url ? `<div class="callout mt">${icon("check")}<div>Open <b class="num">${esc(m.lan.url)}</b> on your phone's browser (same Wi-Fi), then add it to your home screen. Windows may ask to allow NetWatch through the firewall — choose <b>Private networks</b>.</div></div>` : m.lan.error ? `<div class="callout warn mt">${icon("alert")}${esc(m.lan.error)}</div>` : "")) +
      card("sites", "Multi-site", row("This PC's role", "", sel("site_role", s.site_role, [["standalone", "Standalone"], ["hub", "Hub — collects other sites"], ["agent", "Agent — reports to a hub"]])) + row("Site name", "", txt("site_name", s.site_name)) +
        row("Site key", "Shared secret — the same on hub and agents", txt("site_key", s.site_key)) + row("Hub address", "Agents only, e.g. http://hub-pc:8780 (the hub's phone dashboard port)", txt("hub_url", s.hub_url)) +
        `<div class="small muted">A hub receives reports on the phone dashboard port, so the hub PC's firewall must allow it. Across the internet, use a VPN between sites.</div>`) + `</div>`;
    if (this.tab === "data") html = `<div class="grid g-2">` +
      card("folder", "Data", row("Keep history for", "Days", num("retention_days", s.retention_days)) + row("Data folder", esc(m.data_dir), `<button class="btn" id="openData">${icon("folder")}Open</button>`) + row("Version", `NetWatch ${esc(m.version)} on ${esc(m.hostname)}`, `<span class="pill ${m.admin ? "good" : ""}">${m.admin ? "Administrator" : "Standard user"}</span>`)) +
      card("download", "Updates", row("GitHub repository", "owner/name where you publish NetWatch.exe releases", txt("update_repo", s.update_repo, "you/netwatch")) + row("Check automatically", "Every 6 hours", sw("auto_update_check", s.auto_update_check)) +
        `<div id="updBox" class="mt">${m.update.latest ? `<div class="callout">${icon(m.update.available ? "download" : "check")}<div>${m.update.available ? `<b>Version ${esc(m.update.latest)} is available.</b>` : `You're up to date (latest ${esc(m.update.latest)}).`}</div></div>` : ""}</div>
        <div class="row" style="gap:8px;margin-top:10px"><button class="btn" id="updCheck">${icon("refresh")}Check now</button><button class="btn primary" id="updInstall" ${m.update.available ? "" : "disabled"}>${icon("download")}Download & install</button></div>`) + `</div>`;
    $("#setBody").innerHTML = html;
    const on = (id, fn) => { if ($("#" + id)) $("#" + id).onclick = fn; };
    on("ovl", async () => { const r = await API.toggle_overlay(); if (r.error) toast(r.error, "bad"); });
    on("openData", () => API.open_data_folder());
    on("routerTest", async () => { await this.save(true); toast("Signing in to your router…"); const r = await API.router_retry(); toast(r.error ? r.error : "Connected — see the Router page", r.error ? "bad" : "good"); this.s = await API.get_settings(); this.render(); });
    on("weeklyNow", async () => { await this.save(true); const r = await API.send_weekly_now(); const k = Object.keys(r.results || {}); toast(k.length ? "Weekly summary sent" : "Enable a remote channel first", k.length ? "good" : "bad"); });
    on("testRemote", async () => { this.collectInto(); toast("Sending test alert…"); const res = (await API.test_remote(this.payload())).results || {}; const k = Object.keys(res); toast(k.length ? k.map(x => `${x}: ${res[x]}`).join(" · ") : "Enable at least one channel first", k.some(x => res[x] !== "sent") || !k.length ? "bad" : "good"); });
    on("updCheck", async () => { await this.save(true); const st = await API.check_update(); toast(st.error || (st.available ? `Version ${st.latest} available` : "You're up to date"), st.error ? "bad" : "good"); this.s = await API.get_settings(); this.render(); });
    on("updInstall", async () => { toast("Downloading update…"); const d = await API.download_update(); if (d.error) return toast(d.error, "bad"); const a = await API.apply_update(); if (a.error) toast(a.error, "bad"); else toast("Installing — NetWatch will restart", "good"); });
  },
  collectInto() {
    $$("#setBody [data-k]").forEach(el => {
      const k = el.dataset.k; let v = el.type === "checkbox" ? el.checked : el.value;
      if (["targets", "dns_extra", "cloud_custom"].includes(k)) v = String(v).split(",").map(x => x.trim()).filter(Boolean);
      if (k.startsWith("remote.")) this.s.remote[k.slice(7)] = k === "remote.smtp_port" ? (+v || 587) : v; else this.s[k] = v;
    });
  },
  payload() { const p = JSON.parse(JSON.stringify(this.s)); delete p._meta; return p; },
  async save(quiet) {
    this.collectInto();
    const r = await API.save_settings(this.payload());
    if (r.error) return toast(r.error, "bad");
    window.NW_COST = +this.s.downtime_cost_per_hour || 0;
    if (!quiet) toast("Settings saved", "good");
    this.s = await API.get_settings(); this.render();
  },
};

// ============================================================ phone login + boot
function showLogin(msg) {
  document.body.innerHTML = `<div class="login"><div class="card" style="width:320px;text-align:center;padding:28px"><div class="brand-logo" style="margin:0 auto 14px;width:52px;height:52px">${icon("logo")}</div>
    <div class="page-title" style="font-size:22px">NetWatch</div><div class="muted" style="margin:6px 0 18px">Enter your PIN</div>
    <input class="input" id="pin" type="password" inputmode="numeric" autocomplete="current-password" style="text-align:center;font-size:22px;letter-spacing:.3em">
    <button class="btn primary" id="pinGo" style="width:100%;justify-content:center;margin-top:12px">Unlock</button><div class="small bad-t" style="margin-top:10px">${esc(msg || "")}</div></div></div>`;
  const go2 = async () => {
    const r = await fetch("/auth", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ pin: $("#pin").value }) });
    const j = await r.json();
    if (j.token) { try { sessionStorage.setItem("nwtok", j.token); } catch (e) {} location.reload(); } else showLogin(j.error || "Wrong PIN");
  };
  $("#pinGo").onclick = go2; $("#pin").onkeydown = e => { if (e.key === "Enter") go2(); }; $("#pin").focus();
}

function boot() {
  window.addEventListener("hashchange", () => { const id = location.hash.slice(1); if (id && id !== current) go(id); });
  applyChartTheme();
  renderNav();
  go(location.hash.slice(1) || "dashboard");
  pollState();
  API.get_settings().then(s => { if (s && !s.error) window.NW_COST = +s.downtime_cost_per_hour || 0; });
}

window.NW_START = function () {
  if (window.NW_LAN) {
    let tok = null; try { tok = sessionStorage.getItem("nwtok"); } catch (e) {}
    if (tok) { window.NW_TOKEN = tok; document.body.classList.add("lan"); boot(); } else showLogin();
  } else boot();
};
