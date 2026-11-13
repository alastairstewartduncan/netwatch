"""JavaScript-facing API. Every public method is callable from the UI as window.pywebview.api.<name>()."""

import csv
import html
import os
import sys
import time
import webbrowser
from datetime import datetime
from functools import wraps
from pathlib import Path

from . import diag, integrations, winapi
from .engine import VERSION, fmt_duration
from .version import APP_NAME
from .extras import SECRET_FIELDS

PASSWORD_MASK = "********"


def safe(fn):
    @wraps(fn)
    def wrapper(self, *args, **kwargs):
        try:
            return fn(self, *args, **kwargs)
        except Exception as e:
            self._engine.log_error(fn.__name__)
            return {"error": str(e)}
    return wrapper


class Api:
    def __init__(self, engine, quit_cb=None):
        self._engine = engine
        self._x = engine.extras
        self._window = None
        self._quit_cb = quit_cb

    def _set_window(self, window):
        self._window = window

    # ------------------------------------------------------------ dashboard
    @safe
    def get_state(self):
        return self._engine.snapshot()

    # ------------------------------------------------------------ devices
    @safe
    def get_devices(self):
        e = self._engine
        return {"devices": e.device_list(), "scan": dict(e.scan), "net": e.net,
                "vendors_loaded": e.vendors.loaded}

    @safe
    def scan_devices(self):
        return {"started": self._engine.start_scan()}

    @safe
    def update_device(self, key, fields):
        return {"ok": self._engine.update_device(key, fields)}

    @safe
    def forget_device(self, key):
        self._engine.forget_device(key)
        return {"ok": True}

    @safe
    def ping_device(self, key):
        d = self._engine.devices.get(key)
        if not d:
            return {"error": "Unknown device"}
        rtts = [winapi.ping(d["ip"], 1000) for _ in range(4)]
        return {"ip": d["ip"], "rtts": rtts}

    @safe
    def port_scan(self, key):
        return {"ports": self._engine.port_scan(key)}

    @safe
    def wake_device(self, key):
        return {"ok": self._engine.wake_device(key)}

    @safe
    def open_url(self, url):
        webbrowser.open(url)
        return {"ok": True}

    # ------------------------------------------------------------ apps & connections
    @safe
    def get_apps(self):
        return self._engine.apps_view()

    @safe
    def get_connections(self):
        return self._engine.connections()

    @safe
    def relaunch_admin(self):
        winapi.release_single_instance()
        if winapi.relaunch_as_admin():
            if self._quit_cb:
                self._quit_cb()
            return {"ok": True}
        winapi.acquire_single_instance()
        return {"error": "Elevation was cancelled"}

    # ------------------------------------------------------------ Wi-Fi / DNS / services
    @safe
    def get_wifi(self):
        return self._engine.wifi_view()

    @safe
    def get_dns(self):
        return self._engine.dns_view()

    @safe
    def get_services(self):
        return self._engine.services_view()

    @safe
    def save_service(self, check):
        return {"id": self._engine.save_service(check)}

    @safe
    def delete_service(self, cid):
        self._engine.delete_service(cid)
        return {"ok": True}

    @safe
    def run_service_now(self, cid):
        self._engine.run_service_now(cid)
        return {"ok": True}

    # ------------------------------------------------------------ speed test
    @safe
    def start_speedtest(self):
        return {"started": self._engine.start_speedtest("manual")}

    @safe
    def get_speedtest(self):
        e = self._engine
        return {"state": dict(e.speed), "history": e.store.speedtests(limit=60),
                "plan": {"down": e.settings.get("plan_down_mbps"), "up": e.settings.get("plan_up_mbps")},
                "interval": e.settings.get("speedtest_interval_hours")}

    # ------------------------------------------------------------ traceroute
    @safe
    def start_traceroute(self, host):
        return {"started": self._engine.start_traceroute(host)}

    @safe
    def stop_traceroute(self):
        self._engine.stop_traceroute()
        return {"ok": True}

    @safe
    def get_traceroute(self):
        return self._engine.trace_view()

    # ------------------------------------------------------------ history & events
    @safe
    def get_history(self, hours=24):
        return self._engine.store.history(int(hours))

    @safe
    def get_events(self, limit=500):
        return self._engine.store.events(int(limit))

    def _save_path(self, filename, kind):
        if self._window is not None:
            try:
                import webview
                types = {"csv": ("CSV file (*.csv)",), "xlsx": ("Excel workbook (*.xlsx)",)}.get(kind, ("Web page (*.html)",))
                res = self._window.create_file_dialog(webview.SAVE_DIALOG, save_filename=filename, file_types=types)
                if not res:
                    return None
                return res if isinstance(res, str) else res[0]
            except Exception:
                pass
        folder = Path.home() / "Documents" / "NetWatch"
        folder.mkdir(parents=True, exist_ok=True)
        return str(folder / filename)

    @safe
    def export_events(self):
        path = self._save_path(f"netwatch-events-{datetime.now():%Y%m%d}.csv", "csv")
        if not path:
            return {"cancelled": True}
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Time", "Level", "Category", "Event"])
            for e in reversed(self._engine.store.events(100000)):
                w.writerow([datetime.fromtimestamp(e["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
                            e["level"], e["category"], e["message"]])
        return {"path": path}

    @safe
    def export_history_csv(self, hours=168):
        path = self._save_path(f"netwatch-history-{datetime.now():%Y%m%d}.csv", "csv")
        if not path:
            return {"cancelled": True}
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(["Time", "Online %", "Latency ms", "Max latency ms", "Jitter ms", "Packet loss %",
                        "Router ms", "Download Mbps", "Upload Mbps", "Wi-Fi signal %", "DNS ms"])
            for r in self._engine.store.export_minutes(int(hours)):
                w.writerow([datetime.fromtimestamp(r[0]).strftime("%Y-%m-%d %H:%M"),
                            _f(r[1], 100), _f(r[2]), _f(r[3]), _f(r[4]), _f(r[5]), _f(r[6]),
                            _f(r[7], 8 / 1e6), _f(r[8], 8 / 1e6), _f(r[9]), _f(r[10])])
        return {"path": path}

    @safe
    def export_report(self, hours=720):
        h = self._engine.store.history(int(hours))
        path = self._save_path(f"netwatch-isp-report-{datetime.now():%Y%m%d}.html", "html")
        if not path:
            return {"cancelled": True}
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(build_report(h, self._engine))
        try:
            webbrowser.open(Path(path).as_uri())
        except Exception:
            pass
        return {"path": path}

    # ------------------------------------------------------------ settings
    @safe
    def get_settings(self):
        e = self._engine
        s = {k: v for k, v in e.settings.items()}
        s["remote"] = dict(s["remote"])
        if s["remote"].get("smtp_password"):
            s["remote"]["smtp_password"] = PASSWORD_MASK
        for k in SECRET_FIELDS:
            if s.get(k):
                s[k] = PASSWORD_MASK
        for k in ("isp_counts", "gateway_mac", "usage_alerted", "weekly_last", "update_notified", "survey"):
            s.pop(k, None)
        s["start_with_windows"] = winapi.get_start_with_windows()
        s["_meta"] = {"windows": winapi.IS_WINDOWS, "admin": winapi.is_admin(), "data_dir": str(e.data_dir),
                      "version": VERSION, "frozen": bool(getattr(sys, "frozen", False)),
                      "lan": dict(self._x.lan_state), "mqtt": dict(self._x.ha.state), "update": dict(self._x.updater.state),
                      "site_push": dict(self._x.site),
                      "router": {k: v for k, v in self._x.router.state.items()}, "hostname": __import__("socket").gethostname()}
        return s

    @safe
    def save_settings(self, s):
        s = dict(s)
        s.pop("_meta", None)
        s.pop("services", None)
        sww = s.pop("start_with_windows", None)
        remote = s.get("remote")
        if remote and remote.get("smtp_password") == PASSWORD_MASK:
            remote.pop("smtp_password")
        for k in SECRET_FIELDS:
            if k in s:
                if s[k] == PASSWORD_MASK:
                    s.pop(k)
                elif s[k]:
                    s[k] = winapi.protect(str(s[k]))
        for k in ("mqtt_port", "data_cap_gb", "billing_day", "lan_port", "downtime_cost_per_hour", "router_interval"):
            if k in s:
                s[k] = float(s[k] or 0)
        lan_before = (self._engine.settings.get("lan_enabled"), self._engine.settings.get("lan_port"))
        for k in ("ping_interval", "latency_threshold_ms", "loss_threshold_pct", "auto_scan_minutes",
                  "speedtest_interval_hours", "plan_down_mbps", "plan_up_mbps", "speed_alert_pct",
                  "dns_interval", "wifi_signal_alert", "retention_days"):
            if k in s:
                s[k] = float(s[k] or 0)
        if not s.get("targets"):
            return {"error": "Enter at least one ping target"}
        self._engine.save_settings(s)
        if sww is not None and winapi.IS_WINDOWS:
            winapi.set_start_with_windows(bool(sww))
        lan_after = (self._engine.settings.get("lan_enabled"), self._engine.settings.get("lan_port"))
        hook = self._x.ui_hooks.get("lan_restart")
        if hook and (lan_after != lan_before or "lan_pin" in s):
            hook()
        return {"ok": True}

    @safe
    def test_remote(self, s=None):
        if s:
            self.save_settings(s)
        res = self._engine.remote.send("INFO", "Test alert", "This is a test alert from NetWatch. "
                                       "If you can read this, remote alerts are working.", force=True)
        return {"results": res or {}}

    @safe
    def pause_alerts(self, minutes):
        until = time.time() + float(minutes) * 60 if float(minutes) > 0 else 0
        self._engine.save_settings({"alerts_paused_until": until})
        return {"until": until}

    @safe
    def open_data_folder(self):
        path = str(self._engine.data_dir)
        if winapi.IS_WINDOWS:
            os.startfile(path)
        return {"path": path}

    @safe
    def hide_window(self):
        if self._window:
            self._window.hide()
        return {"ok": True}


def _f(v, mult=1.0):
    return "" if v is None else round(v * mult, 2)


def build_report(h, engine):
    s = h["summary"]
    esc = html.escape
    plan_d = engine.settings.get("plan_down_mbps") or 0
    plan_u = engine.settings.get("plan_up_mbps") or 0
    pub = engine.public or {}

    def fmt(v, unit="", dp=1):
        return "—" if v is None else f"{v:.{dp}f}{unit}"

    day_rows = "".join(
        f"<tr><td>{d['date']}</td><td><div class='bar'><span style='width:{max(0, min(100, d['uptime'] or 0)):.1f}%;"
        f"background:{'#16a34a' if (d['uptime'] or 0) >= 99.9 else '#f59e0b' if (d['uptime'] or 0) >= 99 else '#dc2626'}'>"
        f"</span></div></td><td>{fmt(d['uptime'], '%', 2)}</td><td>{fmt_duration(d['outage_s']) if d['outage_s'] else '—'}"
        f"</td><td>{fmt(d['latency'], ' ms', 0)}</td><td>{fmt(d['loss'], '%', 2)}</td>"
        f"<td>{round((d['monitored_min'] or 0) / 60, 1)} h</td></tr>"
        for d in h["days"] if d["monitored_min"])
    out_rows = "".join(
        f"<tr><td>{datetime.fromtimestamp(o['start']):%a %d %b %Y %H:%M}</td><td>{fmt_duration(o['duration'])}</td>"
        f"<td>{esc(o['cause'] or '')}</td></tr>" for o in h["outages"]) or "<tr><td colspan=3>No outages recorded</td></tr>"
    sp_rows = "".join(
        f"<tr><td>{datetime.fromtimestamp(t['ts']):%a %d %b %H:%M}</td><td>{t['down']:.1f}</td><td>{t['up']:.1f}</td>"
        f"<td>{t['ping']:.0f}</td><td>{(100 * t['down'] / plan_d):.0f}%</td></tr>" if plan_d else
        f"<tr><td>{datetime.fromtimestamp(t['ts']):%a %d %b %H:%M}</td><td>{t['down']:.1f}</td><td>{t['up']:.1f}</td>"
        f"<td>{t['ping']:.0f}</td><td>—</td></tr>" for t in h["speedtests"]) or \
        "<tr><td colspan=5>No speed tests in this period</td></tr>"
    days = h["hours"] // 24
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Broadband performance report</title>
<style>
body{{font-family:Segoe UI,system-ui,sans-serif;color:#0f172a;max-width:960px;margin:32px auto;padding:0 20px}}
h1{{margin:0 0 4px;font-size:26px}} h2{{margin-top:36px;font-size:18px;border-bottom:2px solid #e2e8f0;padding-bottom:6px}}
.muted{{color:#64748b}} .grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:20px}}
.kpi{{border:1px solid #e2e8f0;border-radius:12px;padding:14px}} .kpi b{{display:block;font-size:24px;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:14px}} td,th{{padding:7px 8px;border-bottom:1px solid #eef2f7;text-align:left}}
th{{color:#475569;font-weight:600}} .bar{{background:#f1f5f9;border-radius:6px;height:10px;width:160px;overflow:hidden}}
.bar span{{display:block;height:100%}} @media print{{body{{margin:0}}}}
</style></head><body>
<h1>Broadband performance report</h1>
<div class="muted">Last {days} days · generated {datetime.now():%d %B %Y %H:%M} by NetWatch {VERSION}<br>
ISP: {esc(pub.get('isp', 'unknown'))} · Public IP: {esc(pub.get('ip', 'unknown'))}
{f' · Plan: {plan_d:.0f}/{plan_u:.0f} Mbps' if plan_d else ''}</div>
<div class="grid">
<div class="kpi"><span class="muted">Uptime</span><b>{fmt(s['uptime'], '%', 2)}</b></div>
<div class="kpi"><span class="muted">Outages</span><b>{s['outages']}</b><span class="muted">{fmt_duration(s['outage_s'])} total</span></div>
<div class="kpi"><span class="muted">Avg latency</span><b>{fmt(s['latency'], ' ms', 0)}</b></div>
<div class="kpi"><span class="muted">Packet loss</span><b>{fmt(s['loss'], '%', 2)}</b></div>
<div class="kpi"><span class="muted">Avg download (tests)</span><b>{fmt(s['avg_speed_down'], ' Mbps', 0)}</b>
{f"<span class='muted'>{100 * s['avg_speed_down'] / plan_d:.0f}% of plan</span>" if plan_d and s['avg_speed_down'] else ''}</div>
<div class="kpi"><span class="muted">Avg upload (tests)</span><b>{fmt(s['avg_speed_up'], ' Mbps', 0)}</b></div>
<div class="kpi"><span class="muted">Jitter</span><b>{fmt(s['jitter'], ' ms', 1)}</b></div>
<div class="kpi"><span class="muted">Hours monitored</span><b>{(s['monitored_min'] or 0) / 60:.0f}</b></div>
</div>
<h2>Daily availability</h2>
<table><tr><th>Date</th><th></th><th>Uptime</th><th>Downtime</th><th>Latency</th><th>Loss</th><th>Monitored</th></tr>{day_rows}</table>
<h2>Outages</h2><table><tr><th>Started</th><th>Duration</th><th>Likely cause</th></tr>{out_rows}</table>
<h2>Speed tests</h2><table><tr><th>When</th><th>Download Mbps</th><th>Upload Mbps</th><th>Ping ms</th><th>% of plan</th></tr>{sp_rows}</table>
<p class="muted" style="margin-top:30px">Measurements were taken continuously from this PC by pinging public servers every few seconds.
"Router unreachable" outages indicate a local network problem rather than an ISP fault.</p>
</body></html>"""


class ApiV3Mixin:
    """v3 feature endpoints (mixed into Api below)."""

    # ------------------------------------------------------------ security
    @safe
    def get_security(self):
        return self._x.security_view()

    @safe
    def run_security(self, kind):
        from . import security
        x, e = self._x, self._engine
        jobs = {"pc": (security.pc_security_check,), "upnp": (security.upnp_audit,),
                "exposure": (lambda: security.exposure_check((e.public or {}).get("ip")),),
                "dhcp": (lambda: security.dhcp_discover(e.net.get("mac")),),
                "leak": (lambda: diag.leak_test(self._geo_lookup if e.settings.get("geo_enabled") else None),)}
        if kind not in jobs:
            return {"error": "Unknown check"}
        return {"started": x.run_job(kind, *jobs[kind])}

    def _geo_lookup(self, ips):
        got = self._engine.store.geo_get(ips)
        missing = [i for i in ips if i not in got]
        if missing:
            new = diag.geo_batch(missing)
            self._engine.store.geo_put(new)
            got.update(new)
        return got

    @safe
    def block_app(self, path, block=True):
        return {"ok": self._x.block_app(path, bool(block))}

    @safe
    def capture_start(self, seconds=60):
        ok = self._x.capture.start(int(seconds))
        return {"started": ok, "state": dict(self._x.capture.state)}

    @safe
    def capture_stop(self):
        self._x.capture.stop()
        return {"ok": True}

    @safe
    def reveal_file(self, path):
        if winapi.IS_WINDOWS and path and os.path.exists(path):
            import subprocess
            subprocess.Popen(["explorer", "/select,", path])
        return {"ok": True}

    # ------------------------------------------------------------ troubleshooter & tools
    @safe
    def run_troubleshoot(self):
        return {"started": self._x.run_job("troubleshoot", diag.troubleshoot, self._engine)}

    @safe
    def get_troubleshoot(self):
        j = self._x.job("troubleshoot")
        return {**j, "fixes": diag.FIXES, "admin": winapi.is_admin()}

    @safe
    def run_fix(self, fix_id):
        out = diag.run_fix(fix_id, self._engine.net.get("interface"))
        self._engine.event("INFO", "network", f"Ran fix: {diag.FIXES[fix_id]['title']}")
        return {"output": out}

    @safe
    def run_tool(self, kind, arg=None):
        e = self._engine
        tools = {"m365": (diag.m365_test,), "cloud": (lambda: diag.cloud_latency(e.settings.get("cloud_custom")),),
                 "justme": (lambda: diag.is_it_just_me(arg),), "ipv6": (diag.ipv6_health,)}
        if kind not in tools:
            return {"error": "Unknown tool"}
        return {"started": self._x.run_job("tool_" + kind, *tools[kind])}

    @safe
    def get_tool(self, kind):
        return self._x.job("tool_" + kind)

    # ------------------------------------------------------------ usage, timeline, apps
    @safe
    def get_usage(self):
        u = self._x.usage()
        u["apps_today"] = self._engine.store.app_usage(__import__("datetime").datetime.now().strftime("%Y-%m-%d"))
        u["failovers"] = self._engine.store.failovers(__import__("time").time() - 30 * 86400)
        return u

    @safe
    def get_timeline(self, hours=24):
        return self._x.timeline(int(hours))

    @safe
    def get_overnight(self):
        return self._x.overnight()

    @safe
    def get_apps_security(self):
        return self._x.apps_security()

    @safe
    def get_world(self):
        return self._x.world()

    # ------------------------------------------------------------ Wi-Fi extras
    @safe
    def survey_record(self, room):
        return {"record": self._x.survey_record(room)}

    @safe
    def survey_delete(self, room):
        self._x.survey_delete(room)
        return {"ok": True}

    @safe
    def get_survey(self):
        return {"rooms": self._engine.settings.get("survey", [])}

    @safe
    def get_mesh(self):
        return self._x.mesh_view()

    # ------------------------------------------------------------ integrations
    @safe
    def get_dnsfilter(self):
        return self._x.dnsfilter.stats()

    @safe
    def snmp_health(self, key):
        e = self._engine
        d = e.devices.get(key)
        if not d:
            return {"error": "Unknown device"}
        info = integrations.snmp_health(d["ip"], e.settings.get("snmp_community") or "public")
        info["ts"] = __import__("time").time()
        with e.lock:
            d["snmp"] = info
            e.store.save_device(key, d)
        return info

    @safe
    def ask(self, question, history=None):
        e = self._engine
        answer = integrations.ask_claude(winapi.unprotect(e.settings.get("ai_key", "")), e.settings.get("ai_model"),
                                         question, self._x.assistant_context(), history or [])
        return {"answer": answer}

    # ------------------------------------------------------------ router
    @safe
    def get_router(self):
        return self._x.router.view()

    @safe
    def router_poll_now(self):
        snap = self._x.router.poll(manual=True)
        if snap and not self._engine.settings.get("router_enabled"):
            self._engine.save_settings({"router_enabled": True})  # it works, so keep reading it automatically
        return {"ok": True, "snap": bool(snap)}

    @safe
    def router_retry(self):
        self._x.router.retry()
        return self.router_poll_now()

    @safe
    def router_enable(self, on=True):
        self._engine.save_settings({"router_enabled": bool(on)})
        return {"ok": True}

    @safe
    def router_pause(self, minutes):
        self._x.router.pause(minutes)
        return {"ok": True, "paused_until": self._x.router.state["paused_until"]}

    @safe
    def ask_router(self, question=None, history=None):
        e = self._engine
        q = (question or "").strip() or integrations.ROUTER_HEALTH_PROMPT
        answer = integrations.ask_claude(winapi.unprotect(e.settings.get("ai_key", "")), e.settings.get("ai_model"),
                                         q, self._x.router_context(), history or [], system=integrations.ROUTER_SYSTEM)
        return {"answer": answer}

    @safe
    def check_update(self):
        return self._x.updater.check(self._engine.settings.get("update_repo"))

    @safe
    def download_update(self):
        return {"path": self._x.updater.download()}

    @safe
    def apply_update(self):
        self._x.updater.apply_and_restart()
        if self._quit_cb:
            __import__("threading").Timer(0.5, self._quit_cb).start()
        return {"ok": True}

    @safe
    def get_sites(self):
        return self._x.sites_view()

    @safe
    def delete_site(self, name):
        self._engine.store.delete_site(name)
        return {"ok": True}

    @safe
    def send_weekly_now(self):
        res = self._engine.remote.send("INFO", "Weekly summary", self._x.weekly_text(), force=True)
        return {"results": res or {}, "text": self._x.weekly_text()}

    @safe
    def export_inventory(self, fmt="xlsx"):
        ext = {"xlsx": "xlsx", "csv": "csv", "html": "html"}.get(fmt, "xlsx")
        path = self._save_path(f"netwatch-inventory-{__import__('datetime').datetime.now():%Y%m%d}.{ext}",
                               "csv" if ext == "csv" else ext)
        if not path:
            return {"cancelled": True}
        path = self._x.export_inventory(path)
        if ext == "html":
            import webbrowser
            webbrowser.open(Path(path).as_uri())
        return {"path": path}

    @safe
    def toggle_overlay(self):
        hook = self._x.ui_hooks.get("toggle_overlay")
        if not hook:
            return {"error": "The mini overlay is only available in the desktop app"}
        return {"on": hook()}


for _name, _fn in list(ApiV3Mixin.__dict__.items()):
    if not _name.startswith("__"):
        setattr(Api, _name, _fn)


class ApiAboutMixin:
    """About page, first-run setup and what's-new."""

    @safe
    def get_about(self):
        import platform
        import time as _t
        from . import version as V
        e = self._engine

        def size_of(path):
            total = 0
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
            return total

        webview_ver = None
        try:
            import webview
            webview_ver = getattr(webview, "__version__", None)
        except Exception:
            pass
        wv2 = None
        if winapi.IS_WINDOWS:
            try:
                import winreg
                for root, key in ((winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
                                  (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}")):
                    try:
                        with winreg.OpenKey(root, key) as k:
                            wv2 = winreg.QueryValueEx(k, "pv")[0]
                            break
                    except OSError:
                        continue
            except Exception:
                pass
        exe = sys.executable
        install = "Source" if not getattr(sys, "frozen", False) else \
            ("Installed" if os.path.exists(os.path.join(os.path.dirname(exe), "Uninstall NetWatch.exe")) else "Portable")
        win = platform.platform()
        if winapi.IS_WINDOWS:
            try:
                build = sys.getwindowsversion().build
                win = f"Windows {'11' if build >= 22000 else '10'} (build {build})"
            except Exception:
                pass
        db = e.data_dir / "history.db"
        s = e.snapshot()
        return {
            "app": V.APP_NAME, "version": V.VERSION, "build_date": V.BUILD_DATE, "channel": V.CHANNEL,
            "publisher": V.PUBLISHER, "copyright": V.COPYRIGHT, "description": V.DESCRIPTION,
            "changelog": V.CHANGELOG, "credits": V.CREDITS, "services": V.SERVICES,
            "update": dict(self._x.updater.state), "update_repo": e.settings.get("update_repo", ""),
            "system": {
                "Operating system": win, "Install type": install, "Location": os.path.dirname(exe) if install != "Source" else os.getcwd(),
                "Running as": "Administrator" if winapi.is_admin() else "Standard user",
                "Python": platform.python_version(), "pywebview": webview_ver or "—", "WebView2 runtime": wv2 or "—",
                "Computer": platform.node(), "Network adapter": e.net.get("interface") or "—",
                "Monitoring since": datetime.fromtimestamp(e.session["start"]).strftime("%d %b %Y %H:%M"),
                "Running for": fmt_duration(_t.time() - e.session["start"]),
                "History database": f"{(db.stat().st_size if db.exists() else 0) / 1e6:.1f} MB",
                "Data folder size": f"{size_of(e.data_dir) / 1e6:.1f} MB",
                "Devices known": str(s["devices"]["known"]),
            },
            "data_dir": str(e.data_dir),
        }

    @safe
    def support_info(self):
        a = self.get_about()
        lines = [f"{a['app']} {a['version']} ({a['channel']}, built {a['build_date']})"]
        lines += [f"{k}: {v}" for k, v in a["system"].items()]
        log = self._engine.data_dir / "error.log"
        if log.exists():
            tail = log.read_text(encoding="utf-8", errors="replace")[-3000:]
            lines += ["", "Recent errors:", tail]
        return {"text": "\n".join(lines)}

    @safe
    def open_log(self):
        log = self._engine.data_dir / "error.log"
        if not log.exists():
            log.write_text("No errors logged.\n", encoding="utf-8")
        if winapi.IS_WINDOWS:
            os.startfile(str(log))
        return {"path": str(log)}

    @safe
    def get_first_run(self):
        from .version import VERSION
        s = self._engine.settings
        seen = s.get("last_version_seen") or ""
        return {"onboarded": bool(s.get("onboarded")), "last_version_seen": seen, "version": VERSION,
                "show_whats_new": bool(s.get("onboarded")) and seen != VERSION,
                "windows": winapi.IS_WINDOWS, "start_with_windows": winapi.get_start_with_windows()}

    @safe
    def complete_onboarding(self, choices):
        from .version import VERSION
        c = dict(choices or {})
        sww = c.pop("start_with_windows", None)
        allowed = {"plan_down_mbps", "plan_up_mbps", "data_cap_gb", "speedtest_interval_hours", "notify",
                   "notify_new_devices", "theme", "minimize_to_tray"}
        upd = {k: v for k, v in c.items() if k in allowed}
        for k in ("plan_down_mbps", "plan_up_mbps", "data_cap_gb", "speedtest_interval_hours"):
            if k in upd:
                upd[k] = float(upd[k] or 0)
        upd.update(onboarded=True, last_version_seen=VERSION)
        self._engine.save_settings(upd)
        if sww is not None and winapi.IS_WINDOWS:
            winapi.set_start_with_windows(bool(sww))
        if c.get("scan_now"):
            self._engine.start_scan()
        if c.get("speedtest_now"):
            self._engine.start_speedtest("manual")
        return {"ok": True}

    @safe
    def mark_version_seen(self):
        from .version import VERSION
        self._engine.save_settings({"last_version_seen": VERSION})
        return {"ok": True}


for _name, _fn in list(ApiAboutMixin.__dict__.items()):
    if not _name.startswith("__"):
        setattr(Api, _name, _fn)
