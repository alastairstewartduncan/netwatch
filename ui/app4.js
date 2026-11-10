"use strict";
/* NetWatch 3.1 - About / version page, loading screen, first-run setup, what's new */

const fmtLongDate = d => new Date(d + "T12:00:00").toLocaleDateString([], { day: "numeric", month: "long", year: "numeric" });

// ============================================================ About page
PAGES.about = {
  shell() { return `<div id="aboutBody"><div class="empty">${icon("refresh", "spin")}</div></div>`; },
  async init() {
    const a = await API.get_about();
    if (!a || a.error) { $("#aboutBody").innerHTML = `<div class="callout warn">${icon("alert")}${esc(a && a.error)}</div>`; return; }
    this.a = a;
    const latest = a.changelog[0];
    $("#aboutBody").innerHTML = `
      <div class="card about-hero">
        <img src="icon.png" class="about-icon" alt="">
        <div class="grow">
          <div class="about-name">${esc(a.app)}</div>
          <div class="about-ver"><span class="pill info">Version ${esc(a.version)}</span><span class="pill">${esc(a.channel)}</span><span class="muted">Built ${fmtLongDate(a.build_date)}</span></div>
          <div class="muted" style="margin-top:8px">${esc(a.description)} · ${esc(a.copyright)}</div>
        </div>
        <div class="about-actions">
          <button class="btn primary" id="abUpd">${icon("refresh")}Check for updates</button>
          <button class="btn" id="abCopy">${icon("file")}Copy support info</button>
          <div class="row" style="gap:8px"><button class="btn ghost sm" id="abLog">${icon("list")}Error log</button><button class="btn ghost sm" id="abData">${icon("folder")}Data folder</button></div>
        </div>
      </div>
      <div id="abUpdBox"></div>
      <div class="grid g-3 mt">
        <div class="card span-2"><div class="card-head"><div class="card-title">${icon("sparkle")}What's new</div><span class="card-sub">release history</span></div>
          <div class="releases">${a.changelog.map((r, i) => `<details class="release" ${i === 0 ? "open" : ""}><summary><span class="rel-dot ${i === 0 ? "now" : ""}"></span><div class="grow"><div class="row" style="gap:10px"><b>Version ${esc(r.version)}</b>${i === 0 ? '<span class="pill good">Installed</span>' : ""}<span class="muted small">${fmtLongDate(r.date)}</span></div><div class="muted small">${esc(r.title)}</div></div><span class="chev">${smallIcon("down", 16)}</span></summary>
            <ul>${r.changes.map(c => `<li>${esc(c)}</li>`).join("")}</ul></details>`).join("")}</div></div>
        <div class="card"><div class="card-head"><div class="card-title">${icon("pc")}System</div></div>
          <div class="kv sys">${Object.entries(a.system).map(([k, v]) => `<div class="k">${esc(k)}</div><div class="v">${esc(v)}</div>`).join("")}</div></div>
      </div>
      <div class="grid g-2 mt">
        <div class="card"><div class="card-head"><div class="card-title">${icon("shield")}Open-source components</div></div>
          <table class="t"><tr><th>Component</th><th>Licence</th></tr>${a.credits.map(([n, l, u]) => `<tr><td><a href="#" data-url="${esc(u)}">${esc(n)}</a></td><td class="muted">${esc(l)}</td></tr>`).join("")}</table></div>
        <div class="card"><div class="card-head"><div class="card-title">${icon("cloud")}Online services</div></div>
          <table class="t"><tr><th>Service</th><th>Used for</th></tr>${a.services.map(([n, use, u]) => `<tr><td><a href="#" data-url="${esc(u)}">${esc(n)}</a></td><td class="muted">${esc(use)}</td></tr>`).join("")}</table>
          <div class="small muted" style="margin-top:12px">Services marked opt-in are only contacted after you switch them on in Settings. NetWatch has no account, no telemetry and sends nothing about you to its author.</div></div>
      </div>
      <div class="about-foot muted small">${esc(a.app)} is released under the MIT licence. Only scan networks you own or are authorised to manage.<br>Data is stored in <span class="num">${esc(a.data_dir)}</span></div>`;
    this.renderUpdate(a.update, a.update_repo);
    $$("[data-url]").forEach(l => l.onclick = e => { e.preventDefault(); API.open_url(l.dataset.url); });
    $("#abUpd").onclick = async () => {
      if (!this.a.update_repo) { go("settings"); PAGES.settings.tab = "data"; return; }
      $("#abUpd").disabled = true; $("#abUpd").innerHTML = `${icon("refresh", "spin")}Checking…`;
      const st = await API.check_update();
      $("#abUpd").disabled = false; $("#abUpd").innerHTML = `${icon("refresh")}Check for updates`;
      this.renderUpdate(st, this.a.update_repo, true);
    };
    $("#abCopy").onclick = async () => {
      const r = await API.support_info();
      try { await navigator.clipboard.writeText(r.text); toast("Support info copied — paste it into an email or message", "good"); }
      catch (e) { openModal(`<h3 style="margin-top:0">Support information</h3><textarea class="input num" rows="14" style="font-size:12px">${esc(r.text)}</textarea><div class="row" style="justify-content:flex-end;margin-top:12px"><button class="btn" onclick="closeOverlays()">Close</button></div>`); }
    };
    $("#abLog").onclick = () => API.open_log();
    $("#abData").onclick = () => API.open_data_folder();
  },
  renderUpdate(st, repo, checked) {
    const box = $("#abUpdBox"); if (!box) return;
    if (!repo) { box.innerHTML = `<div class="callout mt">${icon("info")}<div>Automatic updates aren't set up yet. Add the GitHub repository you publish releases to in <a href="#settings" onclick="PAGES.settings.tab='data'">Settings → Data & updates</a>.</div></div>`; return; }
    if (st && st.error) { box.innerHTML = `<div class="callout warn mt">${icon("alert")}<div>${esc(st.error)}</div></div>`; return; }
    if (st && st.available) {
      box.innerHTML = `<div class="card mt update-card"><div class="row" style="gap:16px"><div class="ev-ic OK" style="width:44px;height:44px">${icon("download")}</div><div class="grow"><b>NetWatch ${esc(st.latest)} is available</b><div class="small muted">You have ${esc(PAGES.about.a.version)}${st.size ? ` · ${fmtBytes(st.size)} download` : ""}. ${st.installer ? "The installer runs automatically and NetWatch restarts — your settings and history are kept." : ""}</div></div><button class="btn primary" id="abInstall">${icon("download")}Update now</button></div>
        ${st.notes ? `<details class="mt"><summary class="small muted" style="cursor:pointer">Release notes</summary><div class="small" style="white-space:pre-wrap;margin-top:8px;user-select:text">${esc(st.notes)}</div></details>` : ""}</div>`;
      $("#abInstall").onclick = async () => {
        $("#abInstall").disabled = true; $("#abInstall").innerHTML = `${icon("refresh", "spin")}Downloading…`;
        const d = await API.download_update(); if (d.error) { toast(d.error, "bad"); $("#abInstall").disabled = false; return; }
        const r = await API.apply_update(); if (r.error) { toast(r.error, "bad"); $("#abInstall").disabled = false; } else toast("Installing the update — NetWatch will restart", "good");
      };
    } else if (st && st.latest) {
      box.innerHTML = `<div class="callout mt">${icon("check")}<div>You're up to date${checked ? "" : ` (checked ${fmtAgo(st.checked)})`}. Latest release is ${esc(st.latest)}.</div></div>`;
    } else box.innerHTML = "";
  },
};

// ============================================================ first-run setup
const Onboard = {
  step: 0, c: {},
  async maybeShow() {
    if (window.NW_LAN) return;
    const f = await API.get_first_run(); if (!f || f.error) return;
    this.f = f;
    if (!f.onboarded) { this.c = { plan_down_mbps: "", plan_up_mbps: "", data_cap_gb: "", theme: document.documentElement.dataset.theme || "dark", start_with_windows: true, minimize_to_tray: true, notify: true, notify_new_devices: true, auto_speed: true, speedtest_now: true, scan_now: true }; this.step = 0; this.render(); }
    else if (f.show_whats_new) WhatsNew.show();
  },
  render() {
    const c = this.c, steps = 3;
    const dots = `<div class="ob-dots">${[0, 1, 2].map(i => `<i class="${i === this.step ? "on" : i < this.step ? "done" : ""}"></i>`).join("")}</div>`;
    const tog = (k, t, d) => `<label class="ob-row"><div><b>${t}</b><div class="small muted">${d}</div></div><span class="switch"><input type="checkbox" data-c="${k}" ${c[k] ? "checked" : ""}><span></span></span></label>`;
    let body = "";
    if (this.step === 0) body = `<div class="ob-hero"><img src="icon.png" alt=""><div class="ob-title">Welcome to NetWatch</div><div class="muted">Let's get you set up — it takes under a minute.</div></div>
      <div class="ob-feats">${[["shield", "Know when it breaks", "Instant alerts for outages, with whether it's your router or your provider."], ["speed", "Hold your ISP to account", "Scheduled speed tests against your plan, plus a printable report."], ["devices", "See who's connected", "Every device on your network, and a heads-up when a new one joins."], ["doctor", "Fix it yourself", "A troubleshooter that finds the fault and offers one-click fixes."]].map(([ic, t, d]) => `<div class="ob-feat"><div class="ob-ic">${icon(ic)}</div><div><b>${t}</b><div class="small muted">${d}</div></div></div>`).join("")}</div>`;
    if (this.step === 1) body = `<div class="ob-head"><div class="ob-title">Your broadband</div><div class="muted">Used to judge your speed tests. Find these on your bill or your provider's website — or skip for now.</div></div>
      <div class="grid g-2" style="gap:12px"><div class="field"><label>Download speed (Mbps)</label><input class="input num" type="number" data-c="plan_down_mbps" value="${esc(c.plan_down_mbps)}" placeholder="e.g. 80"></div>
      <div class="field"><label>Upload speed (Mbps)</label><input class="input num" type="number" data-c="plan_up_mbps" value="${esc(c.plan_up_mbps)}" placeholder="e.g. 20"></div></div>
      <div class="field"><label>Monthly data allowance (GB) — leave blank if unlimited</label><input class="input num" type="number" data-c="data_cap_gb" value="${esc(c.data_cap_gb)}" placeholder="Unlimited"></div>
      <div class="field"><label>Appearance</label><div class="ob-themes">${[["dark", "Dark"], ["light", "Light"]].map(([v, l]) => `<button class="ob-theme ${c.theme === v ? "on" : ""}" data-theme="${v}"><span class="sw ${v}"></span>${l}</button>`).join("")}</div></div>`;
    if (this.step === 2) body = `<div class="ob-head"><div class="ob-title">How should NetWatch behave?</div><div class="muted">You can change any of these later in Settings.</div></div>
      ${this.f.windows ? tog("start_with_windows", "Start when I sign in", "Monitoring never misses an outage. Starts quietly in the tray.") : ""}
      ${tog("minimize_to_tray", "Keep running in the tray", "Closing the window keeps NetWatch watching in the background.")}
      ${tog("notify", "Desktop notifications", "Pop-ups for outages, slow speeds and other problems.")}
      ${tog("notify_new_devices", "Tell me about new devices", "Alert when something unfamiliar joins your network.")}
      ${tog("auto_speed", "Automatic speed tests", "One every 6 hours (uses ~200–500 MB each on fast lines).")}
      ${tog("speedtest_now", "Run a speed test now", "Get your first result straight away.")}`;
    openModal(`<div class="ob">${dots}<div class="ob-body">${body}</div>
      <div class="row between ob-foot"><button class="btn ghost" id="obSkip">${this.step === 0 ? "Skip setup" : "Back"}</button><button class="btn primary" id="obNext">${this.step === steps - 1 ? `${icon("check")}Start monitoring` : "Continue"}</button></div></div>`);
    $("#modal").classList.add("wide");
    $$("#modal [data-c]").forEach(el => el.onchange = el.oninput = () => { c[el.dataset.c] = el.type === "checkbox" ? el.checked : el.value; });
    $$("#modal [data-theme]").forEach(b => b.onclick = () => { c.theme = b.dataset.theme; window.NW_THEME_PREVIEW = true; document.documentElement.dataset.theme = c.theme; applyChartTheme(); this.render(); });
    $("#obSkip").onclick = () => { if (this.step === 0) this.finish(true); else { this.step--; this.render(); } };
    $("#obNext").onclick = () => { if (this.step < steps - 1) { this.step++; this.render(); } else this.finish(false); };
  },
  async finish(skipped) {
    const c = this.c;
    const payload = skipped ? { theme: c.theme } : {
      plan_down_mbps: c.plan_down_mbps || 0, plan_up_mbps: c.plan_up_mbps || 0, data_cap_gb: c.data_cap_gb || 0, theme: c.theme,
      start_with_windows: c.start_with_windows, minimize_to_tray: c.minimize_to_tray, notify: c.notify, notify_new_devices: c.notify_new_devices,
      speedtest_interval_hours: c.auto_speed ? 6 : 0, speedtest_now: c.speedtest_now };
    await API.complete_onboarding(payload);
    if (STATE) STATE.theme = c.theme;
    setTimeout(() => { window.NW_THEME_PREVIEW = false; }, 2500);
    $("#modal").classList.remove("wide"); closeOverlays();
    if (!skipped) toast(c.speedtest_now ? "All set — your first speed test is running" : "All set — NetWatch is monitoring", "good");
    if (!skipped && c.speedtest_now) setTimeout(() => go("speed"), 600);
  },
};

const WhatsNew = {
  show() {
    const r = (PAGES.about.a && PAGES.about.a.changelog) ? PAGES.about.a.changelog[0] : null;
    const draw = rel => {
      openModal(`<div class="ob"><div class="ob-hero" style="margin-top:4px"><img src="icon.png" alt="" style="width:64px;height:64px"><div class="ob-title">What's new in ${esc(rel.version)}</div><div class="muted">${esc(rel.title)}</div></div>
        <ul class="wn">${rel.changes.map(c => `<li>${smallIcon("check", 15)}<span>${esc(c)}</span></li>`).join("")}</ul>
        <div class="row between ob-foot"><a href="#about" class="btn ghost" id="wnAll">Full release history</a><button class="btn primary" id="wnOk">Got it</button></div></div>`);
      $("#modal").classList.add("wide");
      const done = () => { API.mark_version_seen(); $("#modal").classList.remove("wide"); closeOverlays(); };
      $("#wnOk").onclick = done; $("#wnAll").onclick = e => { e.preventDefault(); done(); go("about"); };
    };
    if (r) draw(r); else API.get_about().then(a => { if (a && !a.error) { PAGES.about.a = a; draw(a.changelog[0]); } });
  },
};

// ============================================================ wire-up: nav, splash, sidebar version
(function () {
  const last = NAV[NAV.length - 1];
  last[1].push(["about", "About"]);
  NAV_ICON.about = "info";
  const origRender = renderNav;
  renderNav = function () {
    origRender();
    $("#brandLogo").innerHTML = `<img src="icon.png" alt="" style="width:38px;height:38px;border-radius:11px;display:block">`;
  };
  const origBoot = boot;
  boot = function () {
    origBoot();
    // sidebar version link
    const foot = document.querySelector(".sidebar-foot");
    if (foot && !document.getElementById("verLink")) {
      const v = document.createElement("a"); v.id = "verLink"; v.href = "#about"; v.className = "ver-link";
      foot.appendChild(v);
    }
    // splash: hide once the first live data arrives (or after 8 s regardless)
    const hide = () => { const s = document.getElementById("splash"); if (s && !s.classList.contains("out")) { s.classList.add("out"); setTimeout(() => s.remove(), 500); Onboard.maybeShow(); } };
    const iv = setInterval(() => { if (STATE) { clearInterval(iv); const v = document.getElementById("verLink"); if (v) v.textContent = `NetWatch ${STATE.version}`; hide(); } }, 150);
    setTimeout(hide, 8000);
  };
})();

window.NW_START();
