"use strict";
/* NetWatch 3.2: Router page - data read directly from the router, visualised, with AI analysis */

// ------------------------------------------------------------ nav entry (Monitor → after Devices)
(function () {
  const mon = NAV[0][1];
  const i = mon.findIndex(x => x[0] === "devices");
  mon.splice(i + 1, 0, ["router", "Router"]);
  NAV_ICON.router = "router";
})();

const RT_KIND = { wired: ["Wired", COL.teal], wifi: ["Wi-Fi", COL.cyan], guest: ["Guest", COL.amber], iot: ["IoT", COL.violet], unknown: ["Other", "#94a3b8"] };
const RT_ORDER = { wired: 0, wifi: 1, iot: 2, guest: 3, unknown: 4 };
const rtConn = c => c.kind === "wired" ? "Wired" : `${c.kind === "guest" ? "Guest " : c.kind === "iot" ? "IoT " : ""}${c.band || "Wi-Fi"}`;
const rtSpeed = v => !isNum(v) ? "" : v >= 1000 ? `${+(v / 1000).toFixed(1)} Gbps` : `${v} Mbps`;

function aiMarkdown(t) {
  const lines = esc(t || "").split("\n");
  let out = "", list = null;
  const close = () => { if (list) { out += `</${list}>`; list = null; } };
  for (let ln of lines) {
    ln = ln.replace(/\*\*(.+?)\*\*/g, "<b>$1</b>").replace(/`([^`]+)`/g, "<code>$1</code>");
    let m;
    if ((m = ln.match(/^#{1,4}\s+(.*)$/))) { close(); out += `<div class="ai-h">${m[1]}</div>`; }
    else if ((m = ln.match(/^\s*[-•*]\s+(.*)$/))) { if (list !== "ul") { close(); out += "<ul>"; list = "ul"; } out += `<li>${m[1]}</li>`; }
    else if ((m = ln.match(/^\s*\d+[.)]\s+(.*)$/))) { if (list !== "ol") { close(); out += "<ol>"; list = "ol"; } out += `<li>${m[1]}</li>`; }
    else if (!ln.trim()) { close(); }
    else { close(); out += `<p>${ln}</p>`; }
  }
  close();
  return out;
}

function portPanel(snap) {
  const ports = snap.ports;
  if (!ports || !ports.length) {
    return `<div class="muted small">Your router's firmware didn't report per-port link speeds through its admin interface, so this panel can't be drawn yet.
      Running <b>tools/router_probe.py</b> once shows which data your router offers.</div>`;
  }
  const w = 100, gap = 12, pad = 22, W = pad * 2 + ports.length * w + (ports.length - 1) * gap, H = 150;
  const g = ports.map((p, i) => {
    const x = pad + i * (w + gap), slow = p.up && isNum(p.speed_mbps) && p.speed_mbps < 1000;
    const col = p.up === false ? "var(--muted)" : slow ? COL.warn : p.up ? COL.good : "#94a3b8";
    const label = p.up === false ? "Not connected" : p.up ? (rtSpeed(p.speed_mbps) || "Connected") : "Unknown";
    const isWan = /wan|internet/i.test(p.name);
    return `<g>
      <rect x="${x}" y="38" width="${w}" height="56" rx="9" fill="var(--surface-2)" stroke="${isWan ? COL.indigo : "var(--border-strong)"}" stroke-width="${isWan ? 2 : 1}"/>
      <rect x="${x + 16}" y="52" width="${w - 32}" height="30" rx="3" fill="#0b1224" stroke="var(--border-strong)"/>
      <rect x="${x + 26}" y="76" width="${w - 52}" height="6" fill="var(--surface-solid)"/>
      <circle cx="${x + 12}" cy="48" r="5" fill="${col}" ${p.up ? `filter="url(#rtGlow)"` : ""}/>
      <text x="${x + w / 2}" y="26" text-anchor="middle" class="rt-port-name">${esc(p.name)}</text>
      <text x="${x + w / 2}" y="114" text-anchor="middle" class="rt-port-speed" fill="${col}">${esc(label)}</text>
      ${p.max_mbps ? `<text x="${x + w / 2}" y="130" text-anchor="middle" class="rt-port-max">port max ${rtSpeed(p.max_mbps)}</text>` : ""}
    </g>`;
  }).join("");
  return `<svg class="rt-ports" viewBox="0 0 ${W} ${H}" preserveAspectRatio="xMidYMid meet"><defs><filter id="rtGlow"><feGaussianBlur stdDeviation="2.4" result="b"/><feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter></defs>
    <rect x="4" y="8" width="${W - 8}" height="${H - 12}" rx="16" fill="none" stroke="var(--border)"/>${g}</svg>
    <div class="legend" style="margin-top:6px"><span><i style="background:${COL.good}"></i>Gigabit or faster</span><span><i style="background:${COL.warn}"></i>Slower than gigabit</span><span><i style="background:var(--muted)"></i>Not connected</span></div>`;
}

function wifiBands(snap) {
  const bands = snap.wifi || [];
  if (!bands.length) return `<div class="muted small">No Wi-Fi details reported.</div>`;
  const st = v => v === true ? `<span class="pill good">On</span>` : v === false ? `<span class="pill">Off</span>` : `<span class="muted small">—</span>`;
  return `<div class="rt-bands">${bands.map(b => `<div class="rt-band">
      <div class="row" style="justify-content:space-between"><b>${esc(b.band)}</b>${st(b.main)}</div>
      <div class="kv" style="grid-template-columns:84px 1fr;margin-top:8px">
        ${b.ssid ? `<div class="k">Network</div><div class="v">${esc(b.ssid)}</div>` : ""}
        ${b.channel != null ? `<div class="k">Channel</div><div class="v num">${esc(b.channel)}${b.auto_channel != null ? ` <span class="muted small">${String(b.auto_channel) === "1" || b.auto_channel === true ? "(auto)" : "(fixed)"}</span>` : ""}</div>` : ""}
        ${b.width ? `<div class="k">Width</div><div class="v">${esc(b.width)}</div>` : ""}
        <div class="k">Guest</div><div class="v">${st(b.guest)}${b.guest_ssid ? ` <span class="small muted">${esc(b.guest_ssid)}</span>` : ""}</div>
        ${b.iot != null ? `<div class="k">IoT</div><div class="v">${st(b.iot)}</div>` : ""}
      </div></div>`).join("")}</div>`;
}

PAGES.router = {
  interval: 15000,
  filter: "all",
  chat: [],
  shell() {
    return head("Router", "Status read directly from your router", `<span class="muted small" id="rtRead"></span>
      <button class="btn" id="rtPause" title="Stop signing in for 30 minutes so you can use the router's own web page">${icon("pause")}Pause 30 min</button>
      <button class="btn primary" id="rtNow">${icon("refresh")}Read now</button>`) + `<div id="rtBody"><div class="empty">${icon("router")}<div>Loading…</div></div></div>`;
  },
  init() {
    $("#rtNow").onclick = async () => {
      $("#rtNow").disabled = true; toast("Reading your router…");
      const r = await API.router_poll_now(); $("#rtNow").disabled = false;
      if (r.error) toast(r.error, "bad"); else toast("Router data updated", "good");
      this.refresh();
    };
    $("#rtPause").onclick = async () => {
      const paused = this.v && this.v.state.paused_until > Date.now() / 1000;
      await API.router_pause(paused ? 0 : 30);
      toast(paused ? "Router checks resumed" : "NetWatch won't sign in to the router for 30 minutes", "good"); this.refresh();
    };
  },
  async refresh() {
    const v = await API.get_router(); if (!v || v.error) return;
    this.v = v;
    const body = $("#rtBody"), st = v.state, s = v.snap;
    const paused = st.paused_until > Date.now() / 1000;
    $("#rtPause").innerHTML = `${icon(paused ? "play" : "pause")}${paused ? "Resume" : "Pause 30 min"}`;
    $("#rtRead").textContent = st.running ? "Reading…" : st.last_ok ? `Read ${fmtAgo(st.last_ok)}` : "";
    if (!v.configured) {
      body.dataset.ready = "";
      body.innerHTML = `<div class="card rt-setup"><div class="row" style="gap:18px;align-items:flex-start"><div class="ev-ic INFO" style="width:48px;height:48px">${icon("router")}</div>
        <div class="grow"><h3 style="margin:0 0 6px">Connect NetWatch to your router</h3>
        <div class="muted">NetWatch can sign in to your router's admin interface (the page at <b class="num">${esc(v.host || "192.168.0.1")}</b>) and read its broadband status, Ethernet port speeds, Wi-Fi settings and the list of connected devices. It then shows them here and lets the AI assistant analyse them.</div>
        <ul class="muted small" style="margin:10px 0 14px 18px;padding:0"><li>Works with TP-Link routers, including ISP-supplied ones (brsk, Sky and others use TP-Link EX / VR models).</li><li>Read-only — nothing on the router is changed.</li><li>The password is stored encrypted with your Windows account.</li></ul>
        <button class="btn primary" id="rtSetup">${icon("settings")}Set up in Settings</button></div></div></div>`;
      $("#rtSetup").onclick = () => { PAGES.settings.tab = "integrations"; go("settings"); };
      return;
    }
    const errBox = st.error ? `<div class="callout ${st.suspended ? "warn" : ""}" style="margin-bottom:16px">${icon("alert")}<div><b>${st.suspended ? "Router sign-in paused." : "Last read failed."}</b> ${esc(st.error)}${s ? ` Showing data from ${fmtAgo(s.ts)}.` : ""}
      ${st.suspended ? `<div style="margin-top:8px"><button class="btn sm" id="rtRetry">${icon("refresh")}Retry</button> <a href="#settings" onclick="PAGES.settings.tab='integrations'">Check the password</a></div>` : ""}</div></div>` : "";
    if (!s) {
      body.dataset.ready = "";
      body.innerHTML = errBox + `<div class="card empty">${icon(st.running ? "refresh" : "router")}<div>${st.running ? "Signing in to your router for the first time…" : "No data from the router yet. Press <b>Read now</b>."}</div></div>`;
      if ($("#rtRetry")) $("#rtRetry").onclick = () => API.router_retry().then(r => { toast(r.error || "Connected", r.error ? "bad" : "good"); this.refresh(); });
      return;
    }
    if (!body.dataset.ready) {
      body.dataset.ready = 1;
      body.innerHTML = `<div id="rtErr"></div>
        <div class="grid g-4" id="rtKpis"></div>
        <div id="rtFind"></div>
        <div class="grid g-3 mt"><div class="card span-2"><div class="card-head"><div class="card-title">${icon("network")}Ethernet ports</div><span class="card-sub">link speed each port negotiated</span></div><div id="rtPorts"></div></div>
          <div class="card"><div class="card-head"><div class="card-title">${icon("wifi")}Wi-Fi bands</div></div><div id="rtBands"></div></div></div>
        <div class="card mt" id="rtAi"></div>
        <div class="grid g-3 mt"><div class="card"><div class="card-head"><div class="card-title">${icon("devices")}How devices connect</div><span class="card-sub" id="rtMixSub"></span></div><div class="chart-box" style="height:210px"><canvas id="rtMix"></canvas></div><div class="legend" id="rtMixLegend" style="margin-top:8px;justify-content:center"></div></div>
          <div class="card span-2"><div class="card-head"><div class="card-title">${icon("clock")}Connected devices over time</div><div class="legend"><span><i style="background:${COL.teal}"></i>Wired</span><span><i style="background:${COL.cyan}"></i>Wi-Fi</span><span><i style="background:${COL.amber}"></i>Guest</span></div></div><div class="chart-box"><canvas id="rtHist"></canvas></div></div></div>
        <div class="card mt" id="rtLoadCard" style="display:none"><div class="card-head"><div class="card-title">${icon("bolt")}Router load</div><div class="legend"><span><i style="background:${COL.pink}"></i>CPU</span><span><i style="background:${COL.indigo}"></i>Memory</span></div></div><div class="chart-box"><canvas id="rtLoad"></canvas></div></div>
        <div class="card mt"><div class="card-head"><div class="card-title">${icon("list")}Devices the router can see</div>
          <div class="seg" id="rtSeg">${[["all", "All"], ["wired", "Wired"], ["wifi", "Wi-Fi"], ["guest", "Guest"], ["unseen", "Not in NetWatch"]].map(([k, l]) => `<button data-f="${k}" class="${this.filter === k ? "on" : ""}">${l}</button>`).join("")}</div></div>
          <div class="table-wrap"><table class="t" id="rtClients"></table></div></div>
        <details class="card mt rt-raw"><summary class="card-title" style="cursor:pointer">${icon("file")}Raw data from the router</summary><pre id="rtRawPre" class="small"></pre></details>`;
      $$("#rtSeg button").forEach(b => b.onclick = () => { this.filter = b.dataset.f; $$("#rtSeg button").forEach(x => x.classList.toggle("on", x === b)); this.drawClients(); });
      this.mix = mkChart($("#rtMix"), { type: "doughnut", data: { labels: [], datasets: [{ data: [], backgroundColor: [], borderWidth: 0, hoverOffset: 6 }] }, options: { maintainAspectRatio: false, cutout: "68%" } });
      this.hist = timeLine($("#rtHist"), { datasets: [{ label: "Wired", color: COL.teal, data: [], fill: false, stepped: true, tension: 0 }, { label: "Wi-Fi", color: COL.cyan, data: [], fill: false, stepped: true, tension: 0 }, { label: "Guest", color: COL.amber, data: [], fill: false, stepped: true, tension: 0 }], yFmt: v => Math.round(v), dateFmt: fmtDateTime, tickFmt: fmtClock });
      this.load = timeLine($("#rtLoad"), { datasets: [{ label: "CPU", color: COL.pink, data: [], fmt: v => v.toFixed(0) + "%" }, { label: "Memory", color: COL.indigo, data: [], fill: false, fmt: v => v.toFixed(0) + "%" }], yFmt: v => v + "%", yMax: 100, dateFmt: fmtDateTime });
      this.drawAi();
    }
    $("#rtErr").innerHTML = errBox;
    if ($("#rtRetry")) $("#rtRetry").onclick = () => API.router_retry().then(r => { toast(r.error || "Connected", r.error ? "bad" : "good"); this.refresh(); });
    this.drawKpis(s); this.drawClients();
    $("#rtFind").innerHTML = (v.findings || []).map(f => `<div class="callout warn mt">${icon("alert")}<div>${esc(f)}</div></div>`).join("");
    $("#rtPorts").innerHTML = portPanel(s);
    $("#rtBands").innerHTML = wifiBands(s);
    // device mix
    const mix = {};
    (s.clients || []).forEach(c => { const k = c.kind === "wired" ? "Wired" : c.kind === "guest" ? "Guest" : c.kind === "iot" ? "IoT" : (c.band || "Wi-Fi"); mix[k] = (mix[k] || 0) + 1; });
    const colors = { Wired: COL.teal, "2.4 GHz": COL.indigo, "5 GHz": COL.cyan, "6 GHz": COL.violet, Guest: COL.amber, IoT: COL.pink, "Wi-Fi": COL.cyan, "Wi-Fi 7 MLO": COL.violet };
    const keys = Object.keys(mix);
    this.mix.data.labels = keys; this.mix.data.datasets[0].data = keys.map(k => mix[k]); this.mix.data.datasets[0].backgroundColor = keys.map(k => colors[k] || "#94a3b8"); this.mix.update("none");
    $("#rtMixLegend").innerHTML = keys.map(k => `<span><i style="background:${colors[k] || "#94a3b8"}"></i>${esc(k)} · ${mix[k]}</span>`).join("");
    $("#rtMixSub").textContent = plural((s.clients || []).length, "device");
    // history
    const h = v.history || [];
    const pts = k => h.filter(p => isNum(p[k])).map(p => ({ x: p.ts, y: p[k] }));
    this.hist.data.datasets[0].data = pts("wired"); this.hist.data.datasets[1].data = pts("wifi"); this.hist.data.datasets[2].data = pts("guest"); this.hist.update("none");
    const cpu = pts("cpu"), mem = pts("mem");
    $("#rtLoadCard").style.display = cpu.length || mem.length ? "" : "none";
    this.load.data.datasets[0].data = cpu; this.load.data.datasets[1].data = mem; this.load.update("none");
    $("#rtRawPre").textContent = JSON.stringify({ model: s.model, hardware: s.hardware, firmware: s.firmware, client: s.client, wan: s.wan, lan: s.lan, raw: s.raw }, null, 2);
  },
  drawKpis(s) {
    const wan = s.wan || {}, c = s.counts || {};
    const up = wan.up === true ? ["good", "Connected"] : wan.up === false ? ["bad", "Down"] : [wan.ip ? "good" : "", wan.ip ? "Has an IP" : "Unknown"];
    const uptime = s.uptime_s || wan.uptime_s;
    const loadRing = (pct, col) => isNum(pct) ? ring(pct / 100, pct > 85 ? COL.bad : pct > 65 ? COL.warn : col, null, 52, 6).replace('<div class="icon"></div>', `<div class="icon"><b class="num small">${pct.toFixed(0)}%</b></div>`) : `<span class="muted">—</span>`;
    $("#rtKpis").innerHTML = `
      <div class="card"><div class="card-head"><div class="card-title">${icon("router")}${esc(s.model || "Router")}</div><span class="pill ${up[0]}">${up[1]}</span></div>
        <div class="kv" style="grid-template-columns:78px 1fr"><div class="k">Firmware</div><div class="v small">${esc(s.firmware || "—")}</div><div class="k">Hardware</div><div class="v small">${esc(s.hardware || "—")}</div></div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("globe")}Broadband</div><span class="card-sub">${esc(wan.conn_type || "")}</span></div>
        <div class="kv" style="grid-template-columns:78px 1fr"><div class="k">Public IP</div><div class="v num">${esc(wan.ip || "—")}</div><div class="k">Gateway</div><div class="v num">${esc(wan.gateway || "—")}</div>${(wan.dns || []).length ? `<div class="k">ISP DNS</div><div class="v num small">${wan.dns.map(esc).join(", ")}</div>` : ""}</div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("devices")}Connected now</div></div>
        <div class="row" style="gap:16px;align-items:flex-end"><div class="kpi-value num">${c.total ?? "—"}</div><div class="small muted" style="line-height:1.6">${c.wired ?? 0} wired · ${c.wifi ?? 0} Wi-Fi${c.guest ? ` · ${c.guest} guest` : ""}${c.iot ? ` · ${c.iot} IoT` : ""}</div></div>
        <div class="small muted" style="margin-top:6px">${uptime ? `${s.uptime_s ? "Router" : "Line"} up ${fmtDur(uptime)}` : ""}</div></div>
      <div class="card"><div class="card-head"><div class="card-title">${icon("bolt")}Router load</div></div>
        <div class="row" style="gap:18px;justify-content:space-around"><div style="text-align:center">${loadRing(s.cpu_pct, COL.pink)}<div class="small muted">CPU</div></div><div style="text-align:center">${loadRing(s.mem_pct, COL.indigo)}<div class="small muted">Memory</div></div></div></div>`;
  },
  drawClients() {
    const all = (this.v && this.v.clients) || [];
    const f = this.filter;
    const rows = all.filter(c => f === "all" || (f === "unseen" ? !c.seen_by_scan : f === "wifi" ? (c.kind === "wifi" || c.kind === "iot") : c.kind === f))
      .sort((a, b) => (RT_ORDER[a.kind] ?? 9) - (RT_ORDER[b.kind] ?? 9) || (a.ip || "").localeCompare(b.ip || "", undefined, { numeric: true }));
    $("#rtClients").innerHTML = `<tr><th>Device</th><th>IP address</th><th>Connection</th><th>MAC</th><th>In NetWatch</th></tr>` + (rows.length ? rows.map(c => {
      const [label, col] = RT_KIND[c.kind] || RT_KIND.unknown;
      const name = c.netwatch_name || c.hostname || "Unnamed device";
      return `<tr ${c.key ? `data-key="${esc(c.key)}" style="cursor:pointer"` : ""}><td><b>${esc(name)}</b>${c.netwatch_name && c.hostname && c.hostname !== c.netwatch_name ? `<div class="small muted">${esc(c.hostname)}</div>` : ""}</td>
        <td class="num">${esc(c.ip || "—")}</td><td><span class="pill" style="border-color:${col}55;color:${col}">${esc(rtConn(c))}</span>${isNum(c.signal) ? ` <span class="small muted num">${c.signal} dBm</span>` : ""}</td>
        <td class="num small muted">${esc(c.mac)}</td><td>${c.seen_by_scan ? `<span class="good-t">${smallIcon("check")}</span>${c.trusted ? ' <span class="small muted">trusted</span>' : ""}` : `<span class="pill warn" title="The router lists it but NetWatch's scan hasn't seen it - it may be asleep, on the guest network or isolated">Router only</span>`}</td></tr>`;
    }).join("") : `<tr><td colspan="5" class="muted">No devices in this view.</td></tr>`);
    $$("#rtClients tr[data-key]").forEach(tr => tr.onclick = () => { go("devices"); });
  },
  drawAi() {
    const box = $("#rtAi"); if (!box) return;
    const sugg = ["Why is one of my ports only 100 Mbps?", "Should I change my Wi-Fi channels?", "Do I need the guest network on?", "Are there devices I don't recognise?", "Is my router or my broadband the weak point?"];
    box.innerHTML = `<div class="card-head"><div class="card-title">${icon("sparkle")}Router insights</div><span class="card-sub">AI analysis of your router's data</span></div>
      <div class="row wrap" style="gap:10px;align-items:center"><button class="btn primary" id="rtAnalyse">${icon("sparkle")}Analyse my router</button><span class="small muted">A health check covering broadband, ports, Wi-Fi, load and connected devices.</span></div>
      <div id="rtChat" class="rt-chat"></div>
      <div class="row wrap" id="rtSugg" style="gap:6px;margin:10px 0">${sugg.map(q => `<button class="btn sm ghost">${esc(q)}</button>`).join("")}</div>
      <div class="row" style="gap:8px"><input class="input" id="rtQ" placeholder="Ask about your router, ports, Wi-Fi or devices…"><button class="btn" id="rtAsk">${icon("chat")}Ask</button></div>
      <div class="small muted" style="margin-top:8px">Powered by Claude. Your router summary (model, settings, connected device names and addresses — never passwords) and this PC's measurements are sent to Anthropic's API with each question. Needs an API key in Settings → Integrations.</div>`;
    const send = async (q, label) => {
      if (this.busy) return;
      this.busy = true;
      this.chat.push({ role: "user", content: label || q }); this.drawChat(true);
      const hist = this.chat.slice(0, -1).filter(m => !m.error).map(m => ({ role: m.role, content: m.content }));
      const r = await API.ask_router(q, hist);
      this.busy = false;
      this.chat.push({ role: "assistant", content: r.error ? `⚠️ ${r.error}` : r.answer, error: !!r.error }); this.drawChat();
    };
    $("#rtAnalyse").onclick = () => send("", "Give me a health check of my router.");
    $("#rtAsk").onclick = () => { const q = $("#rtQ").value.trim(); if (q) { $("#rtQ").value = ""; send(q); } };
    $("#rtQ").onkeydown = e => { if (e.key === "Enter") $("#rtAsk").click(); };
    $$("#rtSugg button").forEach(b => b.onclick = () => send(b.textContent));
    this.drawChat();
  },
  drawChat(thinking) {
    const el = $("#rtChat"); if (!el) return;
    el.style.display = this.chat.length || thinking ? "" : "none";
    el.innerHTML = this.chat.map(m => m.role === "user" ? `<div class="bubble user">${esc(m.content)}</div>` : `<div class="bubble assistant ai-md${m.error ? " err" : ""}">${aiMarkdown(m.content)}</div>`).join("") +
      (thinking ? `<div class="bubble assistant">${smallIcon("refresh")} Reading your router's data…</div>` : "");
    el.scrollTop = 1e9;
  },
};
