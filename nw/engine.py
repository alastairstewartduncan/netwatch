"""The monitoring engine: background workers, live state, alerting and persistence."""

import json
import os
import socket
import statistics
import threading
import time
import traceback
import uuid
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

from . import netops, speedtest, winapi
from .alerts import RemoteNotifier
from .storage import Store

try:
    import psutil
except ImportError:
    psutil = None

from .version import VERSION  # noqa: E402  (single source of truth)

DEFAULT_SETTINGS = {
    "targets": ["1.1.1.1", "8.8.8.8", "bbc.co.uk"],
    "ping_interval": 2,
    "latency_threshold_ms": 150,
    "loss_threshold_pct": 5,
    "auto_scan_minutes": 15,
    "notify": True,
    "notify_new_devices": True,
    "minimize_to_tray": True,
    "theme": "dark",
    "speedtest_interval_hours": 6,
    "plan_down_mbps": 0,
    "plan_up_mbps": 0,
    "speed_alert_pct": 50,
    "dns_extra": ["1.1.1.1", "8.8.8.8", "9.9.9.9"],
    "dns_interval": 30,
    "wifi_signal_alert": 35,
    "retention_days": 90,
    "alerts_paused_until": 0,
    "services": [
        {"id": "google", "name": "Google", "type": "http", "target": "https://www.google.com",
         "interval": 60, "enabled": True},
        {"id": "m365", "name": "Microsoft 365", "type": "http", "target": "https://outlook.office.com",
         "interval": 120, "enabled": True},
        {"id": "router-web", "name": "Router admin page", "type": "tcp", "target": "gateway:80",
         "interval": 120, "enabled": True},
    ],
    "remote": {
        "min_level": "ALERT",
        "email_enabled": False, "smtp_host": "", "smtp_port": 587, "smtp_user": "",
        "smtp_password": "", "smtp_from": "", "email_to": "",
        "teams_enabled": False, "teams_webhook": "",
        "ntfy_enabled": False, "ntfy_server": "https://ntfy.sh", "ntfy_topic": "",
    },
}

DNS_NAMES = {"1.1.1.1": "Cloudflare", "1.0.0.1": "Cloudflare", "8.8.8.8": "Google", "8.8.4.4": "Google",
             "9.9.9.9": "Quad9", "149.112.112.112": "Quad9", "208.67.222.222": "OpenDNS"}
DNS_TEST_DOMAINS = ["www.google.com", "www.bbc.co.uk", "www.microsoft.com", "www.amazon.co.uk", "www.apple.com"]
VIRTUAL_NIC_HINTS = ("loopback", "vethernet", "vmware", "virtualbox", "wsl", "isatap", "teredo",
                     "bluetooth", "pseudo")
CATEGORY_TITLES = {"internet": "Internet", "router": "Router", "latency": "Latency", "loss": "Packet loss",
                   "device": "Devices", "wifi": "Wi-Fi", "dns": "DNS", "service": "Services",
                   "speed": "Speed test", "network": "Network", "app": "NetWatch", "alerts": "Alerts",
                   "security": "Security"}


def _avg(values):
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


class Engine:
    def __init__(self, data_dir):
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        self.settings_path = data_dir / "settings.json"
        self.settings = self._load_settings()
        self.store = Store(data_dir / "history.db")
        self.store.close_open_outages()
        self.vendors = netops.VendorDB(data_dir / "oui.json.gz")
        self.lock = threading.RLock()
        self.stop_evt = threading.Event()
        self.pool = ThreadPoolExecutor(max_workers=16)
        self.notify_cb = None   # fn(title, message) - desktop notification
        self.status_cb = None   # fn(level) - tray icon colour
        self.remote = RemoteNotifier(lambda: self.settings["remote"],
                                     lambda m: self.event("WARN", "alerts", m, notify=False, remote=False))

        # ---- live state
        self.net = {}
        self.public = None
        self.ping_hist = {}
        self.bw_hist = deque(maxlen=180)
        self.last_bw = (0.0, 0.0)
        self.internet_up = None
        self.fail_streak = 0
        self.down_since = None
        self.outage_id = None
        self.gateway_up = None
        self.high_latency = [0, False]
        self.loss_flag = False
        self.status_level = None
        self.session = {"start": time.time(), "rx": 0, "tx": 0, "samples": 0, "up": 0}
        self.recent_events = deque(maxlen=50)
        self.devices = self.store.load_devices()
        self.online = {}
        self.scan = {"running": False, "done": 0, "total": 0, "last": None}
        self.wifi = None
        self.wifi_hist = deque(maxlen=360)
        self.wifi_networks = []
        self.wifi_nets_ts = 0
        self.wifi_weak = [0, False]
        self.dns = {}
        self.dns_fail = 0
        self.dns_round = 0
        self.services = {}
        self.svc_pool = ThreadPoolExecutor(max_workers=6)
        self.app_tracker = winapi.TcpBandwidthTracker()
        self.apps = {"rates": [], "ts": 0}
        self.app_day = {}
        self.pid_names = {}
        self.speed = {"running": False, "phase": "", "progress": 0, "mbps": 0, "result": None, "error": None}
        self.trace = {"running": False, "target": "", "dest": "", "hops": [], "error": None, "done": False}
        self._trace_stop = False
        self._dns_cache = {}
        self._io_last = None
        self._acc = self._new_acc()
        self._last_purge = 0
        self._vendor_try = 0
        for ev in reversed(self.store.events(20)):
            self.recent_events.appendleft(ev)
        last = self.store.speedtests(limit=1)
        self.speed["result"] = last[0] if last else None
        from .extras import Extras
        self.extras = Extras(self)

    # ------------------------------------------------------------------ settings
    def _load_settings(self):
        s = json.loads(json.dumps(DEFAULT_SETTINGS))
        try:
            with open(self.settings_path, encoding="utf-8") as fh:
                saved = json.load(fh)
            remote = {**s["remote"], **saved.get("remote", {})}
            s.update(saved)
            s["remote"] = remote
        except (OSError, ValueError):
            pass
        return s

    def save_settings(self, new):
        with self.lock:
            remote = {**self.settings["remote"], **new.pop("remote", {})}
            pw = remote.get("smtp_password", "")
            if pw and not pw.startswith(("dpapi:", "b64:")):
                remote["smtp_password"] = winapi.protect(pw)
            self.settings.update(new)
            self.settings["remote"] = remote
            self._write_settings()

    def _write_settings(self):
        tmp = self.settings_path.with_suffix(".tmp")
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self.settings, fh, indent=2)
        os.replace(tmp, self.settings_path)

    def alerts_paused(self):
        return time.time() < float(self.settings.get("alerts_paused_until", 0) or 0)

    # ------------------------------------------------------------------ events
    def event(self, level, category, message, notify=False, remote=True):
        ts = time.time()
        eid = self.store.add_event(ts, level, category, message)
        with self.lock:
            self.recent_events.appendleft({"id": eid, "ts": ts, "level": level,
                                           "category": category, "message": message})
        paused = self.alerts_paused()
        title = CATEGORY_TITLES.get(category, "NetWatch")
        allowed = getattr(self, "extras", None) is None or self.extras.allow_notification(level, category)
        if notify and self.settings.get("notify") and not paused and allowed and self.notify_cb:
            try:
                self.notify_cb(title, message)
            except Exception:
                pass
        if remote and level in ("WARN", "ALERT", "OK") and not paused:
            self.pool.submit(self.remote.send, level, title, message)

    def log_error(self, where):
        try:
            with open(self.data_dir / "error.log", "a", encoding="utf-8") as fh:
                fh.write(f"{datetime.now():%Y-%m-%d %H:%M:%S} {where}\n{traceback.format_exc()}\n")
        except OSError:
            pass

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        self.event("INFO", "app", f"NetWatch {VERSION} started")
        self._netinfo()
        jobs = [
            (lambda: max(1, float(self.settings["ping_interval"])), self._ping_round, 0.5),
            (lambda: 1.0, self._bw_sample, 1),
            (lambda: 60, self._netinfo, 60),
            (lambda: 600, self._public_ip, 1),
            (lambda: 5, self._wifi_tick, 2),
            (lambda: max(10, float(self.settings["dns_interval"])), self._dns_round, 4),
            (lambda: 5, self._services_tick, 6),
            (lambda: 2, self._apps_tick, 3),
            (lambda: 60 - time.time() % 60, self._minute_flush, 60 - time.time() % 60),
            (lambda: 30, self._scheduler, 8),
        ]
        for interval, fn, delay in jobs:
            threading.Thread(target=self._loop, args=(interval, fn, delay), daemon=True).start()
        self.extras.start()

    def stop(self):
        self.stop_evt.set()
        try:
            self.extras.stop()
        except Exception:
            pass
        self._trace_stop = True
        if self.outage_id:
            self.store.end_outage(self.outage_id, time.time())
        self._minute_flush()

    def _loop(self, interval, fn, delay):
        if self.stop_evt.wait(delay):
            return
        while not self.stop_evt.is_set():
            t = time.monotonic()
            try:
                fn()
            except Exception:
                self.log_error(fn.__name__)
            if self.stop_evt.wait(max(0.2, interval() - (time.monotonic() - t))):
                return

    def _new_acc(self):
        return {"lat": [], "lat_max": None, "gw": [], "probes": 0, "lost": 0, "online": [],
                "down": 0.0, "up": 0.0, "bw_n": 0, "wifi": [], "dns": []}

    # ------------------------------------------------------------------ network info
    def _netinfo(self):
        info = netops.get_network_info()
        old = self.net.get("gateway")
        with self.lock:
            self.net = info
        if old and info.get("gateway") and old != info["gateway"]:
            self.event("WARN", "network", f"Default gateway changed from {old} to {info['gateway']}", notify=True)

    def _public_ip(self):
        data = netops.fetch_public_ip()
        if not data:
            return
        old = self.public
        with self.lock:
            self.public = data
        if old and old.get("ip") and old["ip"] != data["ip"]:
            self.event("INFO", "network", f"Public IP changed from {old['ip']} to {data['ip']}")

    # ------------------------------------------------------------------ ping / outages
    def _resolve(self, host):
        if netops.is_ipv4(host):
            return host
        c = self._dns_cache.get(host)
        if c and time.monotonic() - c[1] < 300:
            return c[0]
        try:
            ip = socket.gethostbyname(host)
            self._dns_cache[host] = (ip, time.monotonic())
            return ip
        except OSError:
            return c[0] if c else None

    def _probe(self, host):
        ip = self._resolve(host)
        return winapi.ping(ip, 1000) if ip else None

    def _ping_round(self):
        targets = [(t, t) for t in self.settings["targets"]]
        gw = self.net.get("gateway")
        if gw:
            targets.insert(0, ("Router", gw))
        futures = {name: self.pool.submit(self._probe, host) for name, host in targets}
        results = {name: f.result() for name, f in futures.items()}
        ts = time.time()
        external = {k: v for k, v in results.items() if k != "Router"}
        ok = [v for v in external.values() if v is not None]
        raw_up = bool(ok)
        avg = sum(ok) / len(ok) if ok else None

        with self.lock:
            for name, rtt in results.items():
                self.ping_hist.setdefault(name, deque(maxlen=150)).append((ts, rtt))
            for name in list(self.ping_hist):
                if name not in results:
                    del self.ping_hist[name]
            a = self._acc
            if avg is not None:
                a["lat"].append(avg)
                a["lat_max"] = max(a["lat_max"] or 0, max(ok))
            if results.get("Router") is not None:
                a["gw"].append(results["Router"])
            a["probes"] += len(external)
            a["lost"] += len(external) - len(ok)

            self.fail_streak = 0 if raw_up else self.fail_streak + 1
            up = raw_up or (self.fail_streak < 2 and self.internet_up is not False)
            a["online"].append(1 if up else 0)
            self.session["samples"] += 1
            self.session["up"] += up
            prev = self.internet_up
            self.internet_up = up

        # outage transitions
        if prev is None and not up:
            self._outage_begin(ts, results)
        elif prev is not None and up != prev:
            if up:
                lasted = ts - (self.down_since or ts)
                if self.outage_id:
                    self.store.end_outage(self.outage_id, ts)
                self.outage_id = None
                self.event("OK", "internet", f"Internet connection restored after {fmt_duration(lasted)}",
                           notify=True)
                self.pool.submit(self._public_ip)
            else:
                self._outage_begin(ts, results)

        # router
        if "Router" in results:
            gw_up = results["Router"] is not None
            if self.gateway_up is not None and gw_up != self.gateway_up:
                if gw_up:
                    self.event("OK", "router", "Router is responding again")
                else:
                    self.event("WARN", "router", "Router stopped responding to ping", remote=False)
            self.gateway_up = gw_up

        # latency
        thr = float(self.settings["latency_threshold_ms"])
        hl = self.high_latency
        if raw_up and avg > thr:
            hl[0] += 1
            if hl[0] >= 3 and not hl[1]:
                hl[1] = True
                self.event("WARN", "latency", f"High latency: {avg:.0f} ms (alert threshold {thr:.0f} ms)",
                           notify=True)
        elif raw_up:
            if hl[1]:
                self.event("OK", "latency", f"Latency back to normal ({avg:.0f} ms)", remote=False)
            hl[0], hl[1] = 0, False

        # packet loss (last ~30 rounds)
        loss = self.loss_pct()
        if raw_up and loss is not None:
            lthr = float(self.settings["loss_threshold_pct"])
            if loss >= lthr and not self.loss_flag:
                self.loss_flag = True
                self.event("WARN", "loss", f"Packet loss is {loss:.1f}% (alert threshold {lthr:.0f}%)", notify=True)
            elif loss < lthr / 2 and self.loss_flag:
                self.loss_flag = False
                self.event("OK", "loss", f"Packet loss back to {loss:.1f}%", remote=False)
        self._update_status()

    def _outage_begin(self, ts, results):
        self.down_since = ts
        has_router = "Router" in results
        router_down = has_router and results["Router"] is None
        cause = "Router unreachable (local network)" if router_down else ("ISP / internet" if has_router else "Unknown")
        self.outage_id = self.store.start_outage(ts, cause)
        detail = " - your router is also unreachable, so the problem is inside your home network" if router_down \
            else (" - your router is fine, so this looks like an ISP problem" if has_router else "")
        self.event("ALERT", "internet", "Internet connection lost" + detail, notify=True)

    def loss_pct(self, rounds=30):
        with self.lock:
            vals = [r for name, d in self.ping_hist.items() if name != "Router" for _, r in list(d)[-rounds:]]
        if not vals:
            return None
        return 100 * sum(1 for v in vals if v is None) / len(vals)

    def _update_status(self):
        level = self.status()["level"]
        if level != self.status_level:
            self.status_level = level
            if self.status_cb:
                try:
                    self.status_cb(level)
                except Exception:
                    pass

    def status(self):
        if self.internet_up is None:
            return {"level": "unknown", "title": "Starting up", "detail": "Taking the first measurements"}
        if not self.internet_up:
            where = {False: "Your router isn't responding either", True: "Your router is fine - likely an ISP problem",
                     None: "No router detected"}[self.gateway_up]
            return {"level": "bad", "title": "Internet is down",
                    "detail": f"{where}. Down for {fmt_duration(time.time() - (self.down_since or time.time()))}."}
        issues = []
        if self.high_latency[1]:
            issues.append("high latency")
        if self.loss_flag:
            issues.append("packet loss")
        if self.wifi_weak[1]:
            issues.append("weak Wi-Fi signal")
        if self.dns_fail >= 3:
            issues.append("DNS problems")
        down_svcs = [s["name"] for s in self.services.values() if s.get("ok") is False]
        if down_svcs:
            issues.append(f"{len(down_svcs)} service{'s' if len(down_svcs) > 1 else ''} down")
        if issues:
            return {"level": "warn", "title": "Connected, with issues", "detail": ", ".join(issues).capitalize()}
        return {"level": "good", "title": "Everything looks good", "detail": "Your connection is healthy"}

    # ------------------------------------------------------------------ bandwidth
    def _io_totals(self):
        rx = tx = 0
        for name, s in psutil.net_io_counters(pernic=True).items():
            n = name.lower()
            if n == "lo" or any(h in n for h in VIRTUAL_NIC_HINTS):
                continue
            rx += s.bytes_recv
            tx += s.bytes_sent
        return rx, tx

    def _bw_sample(self):
        if psutil is None:
            return
        rx, tx = self._io_totals()
        t = time.monotonic()
        if self._io_last:
            lrx, ltx, lt = self._io_last
            dt = max(1e-3, t - lt)
            drx, dtx = max(0, rx - lrx), max(0, tx - ltx)
            down, up = drx / dt, dtx / dt
            with self.lock:
                self.session["rx"] += drx
                self.session["tx"] += dtx
                self.last_bw = (down, up)
                self.bw_hist.append((time.time(), down, up))
                self._acc["down"] += down
                self._acc["up"] += up
                self._acc["bw_n"] += 1
        self._io_last = (rx, tx, t)

    # ------------------------------------------------------------------ minute aggregation
    def _minute_flush(self):
        with self.lock:
            a, self._acc = self._acc, self._new_acc()
        if not a["online"] and not a["bw_n"]:
            return
        lat = a["lat"]
        jitter = statistics.mean(abs(x - y) for x, y in zip(lat, lat[1:])) if len(lat) > 1 else None
        row = {"ts": int(time.time() // 60 * 60),
               "online": _avg(a["online"]), "latency": _avg(lat), "latency_max": a["lat_max"],
               "jitter": jitter, "loss": 100 * a["lost"] / a["probes"] if a["probes"] else None,
               "gw_latency": _avg(a["gw"]),
               "down": a["down"] / a["bw_n"] if a["bw_n"] else None,
               "up": a["up"] / a["bw_n"] if a["bw_n"] else None,
               "wifi_signal": _avg(a["wifi"]), "dns_ms": _avg(a["dns"])}
        self.store.add_minute(row)
        day = datetime.now().strftime("%Y-%m-%d")
        with self.lock:
            usage, self.app_day = self.app_day, {}
        for proc, (bi, bo) in usage.items():
            self.store.add_app_usage(day, proc, bi, bo)

    # ------------------------------------------------------------------ scheduler
    def _scheduler(self):
        now = time.time()
        mins = int(self.settings.get("auto_scan_minutes") or 0)
        last = self.scan.get("last") or 0
        if not self.scan["running"] and (last == 0 or (mins > 0 and now - last >= mins * 60)):
            self.start_scan()
        hours = float(self.settings.get("speedtest_interval_hours") or 0)
        lr = self.speed.get("result")
        if hours > 0 and self.internet_up and not self.speed["running"] and now - self.session["start"] > 120:
            if not lr or now - lr["ts"] >= hours * 3600:
                self.start_speedtest("scheduled")
        if (not self.vendors.loaded or self.vendors.age_days() > 30) and now - self._vendor_try > 6 * 3600:
            self._vendor_try = now
            self.pool.submit(self._update_vendors)
        if now - self._last_purge > 86400:
            self._last_purge = now
            self.store.purge(int(self.settings.get("retention_days") or 90))

    def _update_vendors(self):
        if self.vendors.update():
            with self.lock:
                for key, d in self.devices.items():
                    if d.get("mac"):
                        d["vendor"] = self.vendors.lookup(d["mac"])
                        d["type"] = netops.guess_type(d)
                        self.store.save_device(key, d)

    # ------------------------------------------------------------------ devices
    def start_scan(self):
        with self.lock:
            if self.scan["running"]:
                return False
            if not self.net.get("network"):
                self._netinfo()
            if not self.net.get("network"):
                return False
            self.scan.update(running=True, done=0, total=0)
        info = dict(self.net)

        def progress(d, t):
            self.scan["done"], self.scan["total"] = d, t

        def work():
            try:
                self._apply_scan(netops.scan_network(info, progress))
            except Exception:
                self.log_error("scan")
            finally:
                self.scan["running"] = False
                self.scan["last"] = time.time()
        threading.Thread(target=work, daemon=True).start()
        return True

    def _apply_scan(self, results):
        baseline = not self.devices
        now = time.time()
        new_devices = []
        online = {}
        with self.lock:
            for r in results:
                key = r.get("mac") or f"IP:{r['ip']}"
                d = self.devices.get(key)
                if d is None:
                    d = {"key": key, "name": "", "first_seen": now, "notes": "", "ports": None}
                    self.devices[key] = d
                    if not baseline and not r.get("self"):
                        new_devices.append(d)
                d.update(ip=r["ip"], mac=r.get("mac", ""), last_seen=now,
                         self=bool(r.get("self")), gateway=bool(r.get("gateway")))
                if r.get("hostname"):
                    d["hostname"] = r["hostname"]
                if d.get("mac") and (not d.get("vendor") or d["vendor"] == ""):
                    d["vendor"] = self.vendors.lookup(d["mac"])
                if r.get("self") and not d.get("name"):
                    d["name"] = "This PC"
                if r.get("gateway") and not d.get("name"):
                    d["name"] = "Router"
                d["type"] = netops.guess_type(d)
                online[key] = {"rtt": r.get("rtt")}
                self.store.save_device(key, d)
            self.online = online
        if baseline:
            self.event("INFO", "device", f"First scan complete: {len(results)} device{'s' if len(results) != 1 else ''} recorded as your baseline")
        for d in new_devices:
            label = d.get("hostname") or netops.short_vendor(d.get("vendor", "")) or d.get("mac") or "unknown"
            self.event("ALERT", "device", f"New device joined your network: {d['ip']} ({label})",
                       notify=bool(self.settings.get("notify_new_devices")))

    def device_list(self):
        day = time.time() - 86400
        out = []
        with self.lock:
            for key, d in self.devices.items():
                o = self.online.get(key)
                item = dict(d)
                item["online"] = o is not None
                item["rtt"] = o.get("rtt") if o else None
                item["is_new"] = d.get("first_seen", 0) > day
                item["vendor_short"] = netops.short_vendor(d.get("vendor", ""))
                item["display_type"] = d.get("type_override") or d.get("type") or "device"
                out.append(item)
        return out

    def update_device(self, key, fields):
        with self.lock:
            d = self.devices.get(key)
            if not d:
                return False
            for k in ("name", "notes", "type_override", "trusted"):
                if k in fields:
                    d[k] = fields[k]
            self.store.save_device(key, d)
        return True

    def forget_device(self, key):
        with self.lock:
            self.devices.pop(key, None)
            self.online.pop(key, None)
        self.store.delete_device(key)

    def port_scan(self, key):
        d = self.devices.get(key)
        if not d:
            return []
        ports = netops.port_scan(d["ip"])
        with self.lock:
            d["ports"] = ports
            d["ports_ts"] = time.time()
            d["type"] = netops.guess_type(d)
            self.store.save_device(key, d)
        return ports

    def wake_device(self, key):
        d = self.devices.get(key)
        if not d or not d.get("mac"):
            raise ValueError("No MAC address known for this device")
        addrs = ["255.255.255.255"]
        if self.net.get("network"):
            import ipaddress
            addrs.append(str(ipaddress.IPv4Network(self.net["network"]).broadcast_address))
        netops.wake_on_lan(d["mac"], addrs)
        self.event("INFO", "device", f"Wake-on-LAN packet sent to {d.get('name') or d.get('ip')}")
        return True

    # ------------------------------------------------------------------ Wi-Fi
    def _wifi_tick(self):
        if not winapi.IS_WINDOWS:
            return
        info = netops.wifi_status()
        prev = self.wifi
        try:
            self.extras.on_wifi(prev, info)
        except Exception:
            self.log_error("on_wifi")
        with self.lock:
            self.wifi = info
            if info and info.get("connected") and info.get("signal") is not None:
                self.wifi_hist.append((time.time(), info["signal"], info.get("rx_rate"), info.get("tx_rate")))
                self._acc["wifi"].append(info["signal"])
        if time.time() - self.wifi_nets_ts > 60 and info:
            self.wifi_nets_ts = time.time()
            nets = netops.wifi_networks()
            with self.lock:
                self.wifi_networks = nets
        if not info or info.get("error"):
            return
        was = prev.get("connected") if prev and not prev.get("error") else None
        if was is True and not info["connected"]:
            self.event("WARN", "wifi", f"Wi-Fi disconnected from {prev.get('ssid', 'network')}", notify=True)
        elif was is False and info["connected"]:
            self.event("OK", "wifi", f"Wi-Fi reconnected to {info.get('ssid', 'network')}", remote=False)
        elif was and info["connected"] and prev.get("bssid") and info.get("bssid") != prev.get("bssid"):
            self.event("INFO", "wifi", f"Roamed to access point {info.get('bssid')} (channel {info.get('channel')})")
        thr = float(self.settings.get("wifi_signal_alert") or 0)
        w = self.wifi_weak
        if info["connected"] and info.get("signal") is not None and thr:
            if info["signal"] < thr:
                w[0] += 1
                if w[0] >= 6 and not w[1]:
                    w[1] = True
                    self.event("WARN", "wifi", f"Weak Wi-Fi signal: {info['signal']:.0f}%", notify=True, remote=False)
            else:
                if w[1] and info["signal"] > thr + 10:
                    self.event("OK", "wifi", f"Wi-Fi signal recovered to {info['signal']:.0f}%", remote=False)
                    w[1] = False
                w[0] = 0

    def wifi_view(self):
        with self.lock:
            nets = list(self.wifi_networks)
            info = dict(self.wifi) if self.wifi else None
            hist = list(self.wifi_hist)
        channels = {}
        for n in nets:
            ch = n.get("channel")
            if isinstance(ch, int):
                c = channels.setdefault(ch, {"channel": ch, "count": 0, "band": n.get("band", ""), "strongest": 0})
                c["count"] += 1
                c["strongest"] = max(c["strongest"], n.get("signal") or 0)
        rec = None
        if info and isinstance(info.get("channel"), int) and info["channel"] <= 14:
            load = {ch: sum((n.get("signal") or 0) for n in nets if isinstance(n.get("channel"), int)
                            and abs(n["channel"] - ch) <= 2 and n.get("bssid") != info.get("bssid"))
                    for ch in (1, 6, 11)}
            best = min(load, key=load.get)
            cur_load = sum((n.get("signal") or 0) for n in nets if isinstance(n.get("channel"), int)
                           and abs(n["channel"] - info["channel"]) <= 2 and n.get("bssid") != info.get("bssid"))
            if best != info["channel"] and load[best] < cur_load * 0.6:
                rec = f"Channel {best} is less crowded than your current channel {info['channel']}. " \
                      f"Changing it in your router settings may improve speed and reliability."
        return {"supported": winapi.IS_WINDOWS, "info": info, "history": hist[-240:],
                "networks": sorted(nets, key=lambda n: -(n.get("signal") or 0)),
                "channels": sorted(channels.values(), key=lambda c: c["channel"]), "recommendation": rec}

    # ------------------------------------------------------------------ DNS
    def _dns_servers(self):
        servers = []
        for s in winapi.system_dns_servers():
            servers.append((s, f"Your DNS ({DNS_NAMES.get(s, s)})", True))
        for s in self.settings.get("dns_extra", []):
            if s not in [x[0] for x in servers]:
                servers.append((s, DNS_NAMES.get(s, s), False))
        return servers

    def _dns_round(self):
        servers = self._dns_servers()
        domain = DNS_TEST_DOMAINS[self.dns_round % len(DNS_TEST_DOMAINS)]
        self.dns_round += 1
        futures = [(s, label, sysd, self.pool.submit(netops.dns_query, s, domain)) for s, label, sysd in servers]
        ts = time.time()
        sys_ok, sys_ms, others_ok = [], [], []
        for s, label, sysd, f in futures:
            ms, ok, _ = f.result()
            with self.lock:
                e = self.dns.setdefault(s, {"server": s, "label": label, "system": sysd, "hist": deque(maxlen=120)})
                e["label"], e["system"] = label, sysd
                e["hist"].append((ts, ms if ok else None))
            self.store.add_dns_stat(ts, s, ms if ok else None, 1.0 if ok else 0.0)
            if sysd:
                sys_ok.append(ok)
                if ok and ms is not None:
                    sys_ms.append(ms)
            else:
                others_ok.append(ok)
        with self.lock:
            active = {s for s, _, _ in servers}
            for s in list(self.dns):
                if s not in active:
                    del self.dns[s]
            if sys_ms:
                self._acc["dns"].append(_avg(sys_ms))
        if sys_ok and not any(sys_ok) and any(others_ok):
            self.dns_fail += 1
            if self.dns_fail == 3:
                self.event("ALERT", "dns", "Your DNS server isn't answering, but public DNS servers are. "
                           "Websites may fail to load even though the connection is up.", notify=True)
        else:
            if self.dns_fail >= 3:
                self.event("OK", "dns", "Your DNS server is answering again", remote=False)
            self.dns_fail = 0

    def dns_view(self):
        out = []
        with self.lock:
            for s, e in self.dns.items():
                vals = [v for _, v in e["hist"]]
                okv = [v for v in vals if v is not None]
                out.append({"server": s, "label": e["label"], "system": e["system"],
                            "avg": _avg(okv[-20:]), "median": statistics.median(okv[-20:]) if okv else None,
                            "last": vals[-1] if vals else None,
                            "success": 100 * len(okv) / len(vals) if vals else None,
                            "hist": [(t, v) for t, v in e["hist"]][-60:]})
        out.sort(key=lambda x: (not x["system"], x["avg"] if x["avg"] is not None else 9e9))
        rec = None
        sysd = [x for x in out if x["system"] and x["avg"] is not None]
        pub = [x for x in out if not x["system"] and x["avg"] is not None and (x["success"] or 0) > 95]
        if sysd and pub:
            best = min(pub, key=lambda x: x["avg"])
            mine = min(sysd, key=lambda x: x["avg"])
            if best["avg"] < mine["avg"] * 0.7 and mine["avg"] - best["avg"] > 10:
                rec = (f"{best['label']} ({best['server']}) answers about {mine['avg'] - best['avg']:.0f} ms faster "
                       f"than your current DNS. Switching your router or PC to it may make browsing feel snappier.")
        return {"servers": out, "recommendation": rec, "failing": self.dns_fail >= 3}

    # ------------------------------------------------------------------ service checks
    def _services_tick(self):
        now = time.time()
        for check in self.settings.get("services", []):
            if not check.get("enabled", True):
                continue
            st = self.services.setdefault(check["id"], {"id": check["id"], "name": check["name"], "ok": None,
                                                        "ms": None, "detail": "", "ts": 0, "running": False,
                                                        "hist": deque(maxlen=60), "fails": 0})
            st["name"] = check["name"]
            if st["running"] or now - st["ts"] < max(15, int(check.get("interval", 60))):
                continue
            st["running"] = True
            self.svc_pool.submit(self._run_service, dict(check))

    def _run_service(self, check):
        st = self.services[check["id"]]
        try:
            target = check.get("target", "").replace("gateway", self.net.get("gateway") or "192.168.1.1")
            ok, ms, detail = netops.run_check({**check, "target": target})
        except Exception as e:
            ok, ms, detail = False, None, str(e)[:80]
        ts = time.time()
        prev = st["ok"]
        st.update(ms=ms, detail=detail, ts=ts, running=False)
        st["hist"].append((ts, ms if ok else None))
        self.store.add_service_result(ts, check["id"], ok, ms, detail)
        # require 2 consecutive failures before alerting
        st["fails"] = 0 if ok else st["fails"] + 1
        effective = ok if (ok or st["fails"] >= 2 or prev is None) else prev
        st["ok"] = effective
        if prev is not None and effective != prev and self.internet_up:
            if effective:
                self.event("OK", "service", f"{check['name']} is back up ({detail})", notify=True)
            else:
                self.event("ALERT", "service", f"{check['name']} is down: {detail}", notify=True)

    def run_service_now(self, cid):
        st = self.services.get(cid)
        if st:
            st["ts"] = 0
        self._services_tick()

    def services_view(self):
        since = time.time() - 86400
        out = []
        for check in self.settings.get("services", []):
            st = self.services.get(check["id"], {})
            up, avg_ms = self.store.service_uptime(check["id"], since)
            out.append({**check, "ok": st.get("ok"), "ms": st.get("ms"), "detail": st.get("detail", ""),
                        "cert": self.extras.certs.get(check["id"]),
                        "ts": st.get("ts"), "uptime": None if up is None else up * 100, "avg_ms": avg_ms,
                        "hist": list(st.get("hist", []))})
        return out

    def save_service(self, check):
        with self.lock:
            services = self.settings.setdefault("services", [])
            if not check.get("id"):
                check["id"] = uuid.uuid4().hex[:8]
                services.append(check)
            else:
                for i, c in enumerate(services):
                    if c["id"] == check["id"]:
                        services[i] = {**c, **check}
                        break
                else:
                    services.append(check)
            self.services.pop(check["id"], None)
            self._write_settings()
        return check["id"]

    def delete_service(self, cid):
        with self.lock:
            self.settings["services"] = [c for c in self.settings.get("services", []) if c["id"] != cid]
            self.services.pop(cid, None)
            self._write_settings()

    # ------------------------------------------------------------------ per-app bandwidth
    def _pid_name(self, pid):
        n = self.pid_names.get(pid)
        if n is None:
            try:
                n = psutil.Process(pid).name() if pid else "System"
            except Exception:
                n = f"PID {pid}"
            self.pid_names[pid] = n
        return n

    def _apps_tick(self):
        if not self.app_tracker.available or psutil is None:
            return
        t = time.monotonic()
        deltas = self.app_tracker.sample()
        dt = max(0.5, t - self.apps.get("_t", t - 2))
        per = {}
        for pid, (bi, bo) in deltas.items():
            name = self._pid_name(pid)
            a = per.setdefault(name, [0, 0, set()])
            a[0] += bi
            a[1] += bo
            a[2].add(pid)
        rates = [{"process": n, "down": v[0] / dt, "up": v[1] / dt, "pids": sorted(v[2])}
                 for n, v in per.items() if v[0] or v[1]]
        rates.sort(key=lambda r: -(r["down"] + r["up"]))
        with self.lock:
            self.apps = {"rates": rates[:30], "ts": time.time(), "_t": t}
            for n, v in per.items():
                cur = self.app_day.get(n, (0, 0))
                self.app_day[n] = (cur[0] + v[0], cur[1] + v[1])
        if len(self.pid_names) > 2000:
            self.pid_names.clear()

    def connections(self):
        if psutil is None:
            return {"rows": [], "by_process": []}
        rows, by = [], {}
        for c in psutil.net_connections(kind="inet"):
            pid = c.pid or 0
            name = self._pid_name(pid)
            remote = f"{c.raddr.ip}:{c.raddr.port}" if c.raddr else ""
            rows.append({"process": name, "pid": pid, "proto": "TCP" if c.type == socket.SOCK_STREAM else "UDP",
                         "local": f"{c.laddr.ip}:{c.laddr.port}" if c.laddr else "",
                         "remote": remote, "remote_ip": c.raddr.ip if c.raddr else "",
                         "status": c.status if c.status != "NONE" else ""})
            if remote:
                by[name] = by.get(name, 0) + 1
        return {"rows": rows, "by_process": sorted(({"process": k, "count": v} for k, v in by.items()),
                                                   key=lambda x: -x["count"])[:12]}

    def apps_view(self):
        with self.lock:
            rates = list(self.apps.get("rates", []))
        return {"available": self.app_tracker.available, "admin": winapi.is_admin(),
                "windows": winapi.IS_WINDOWS, "rates": rates,
                "today": self.store.app_usage(datetime.now().strftime("%Y-%m-%d"))}

    # ------------------------------------------------------------------ speed test
    def start_speedtest(self, trigger="manual"):
        if self.speed["running"]:
            return False
        self.speed.update(running=True, phase="starting", progress=0, mbps=0, error=None, live=[])

        def progress(phase, frac, mbps):
            self.speed.update(phase=phase, progress=frac, mbps=mbps)
            if phase in ("download", "upload") and mbps:
                self.speed["live"].append((phase, round(mbps, 1)))

        def work():
            try:
                r = speedtest.run(progress, stop=self.stop_evt.is_set)
                self.store.add_speedtest(r, trigger)
                self.speed["result"] = {**r, "trigger": trigger}
                plan_d = float(self.settings.get("plan_down_mbps") or 0)
                pct = float(self.settings.get("speed_alert_pct") or 0)
                msg = f"Speed test: {r['down']:.0f} Mbps down / {r['up']:.0f} Mbps up, {r['ping']:.0f} ms ping" + \
                      (f", bufferbloat grade {r['grade']}" if r.get("grade") else "")
                if plan_d and pct and r["down"] < plan_d * pct / 100:
                    self.event("WARN", "speed", f"{msg} - only {100 * r['down'] / plan_d:.0f}% of your "
                               f"{plan_d:.0f} Mbps plan", notify=True)
                else:
                    self.event("INFO", "speed", msg)
            except Exception as e:
                self.speed["error"] = str(e)
                self.event("WARN", "speed", f"Speed test failed: {e}", remote=False)
            finally:
                self.speed.update(running=False, phase="done")
        threading.Thread(target=work, daemon=True).start()
        return True

    # ------------------------------------------------------------------ traceroute
    def start_traceroute(self, host):
        if self.trace["running"]:
            return False
        host = (host or "").strip() or "8.8.8.8"
        self._trace_stop = False
        self.trace = {"running": True, "target": host, "dest": "", "hops": [], "error": None, "done": False}

        def on_hop(hop):
            hops = self.trace["hops"]
            if hops and hops[-1]["hop"] == hop["hop"]:
                hops[-1] = dict(hop)
            else:
                hops.append(dict(hop))

        def work():
            try:
                dest, _ = netops.traceroute(host, on_hop=on_hop, should_stop=lambda: self._trace_stop)
                self.trace["dest"] = dest
            except Exception as e:
                self.trace["error"] = str(e)
            finally:
                self.trace["running"] = False
                self.trace["done"] = True
        threading.Thread(target=work, daemon=True).start()
        return True

    def stop_traceroute(self):
        self._trace_stop = True

    def trace_view(self):
        t = dict(self.trace)
        hops = [dict(h) for h in t["hops"]]
        worst, prev = None, 0
        for h in hops:
            if h["avg"] is not None:
                jump = h["avg"] - prev
                if jump > 15 and (worst is None or jump > worst[1]):
                    worst = (h["hop"], jump)
                prev = max(prev, h["avg"])
        t["hops"] = hops
        t["analysis"] = (f"The biggest delay is added at hop {worst[0]} (+{worst[1]:.0f} ms)." if worst else
                         ("No significant latency jumps along the route." if t["done"] and hops else None))
        return t

    # ------------------------------------------------------------------ dashboard snapshot
    def snapshot(self):
        now = time.time()
        with self.lock:
            lat_series = {n: [(round(t, 1), r) for t, r in d] for n, d in self.ping_hist.items()}
            bw = [(round(t, 1), d, u) for t, d, u in self.bw_hist]
            targets = []
            for n, d in self.ping_hist.items():
                vals = [r for _, r in d]
                ok = [v for v in vals[-30:] if v is not None]
                targets.append({"name": n, "last": vals[-1] if vals else None, "avg": _avg(ok),
                                "loss": 100 * (len(vals[-30:]) - len(ok)) / len(vals[-30:]) if vals else None})
            ext = [t["last"] for t in targets if t["name"] != "Router" and t["last"] is not None]
            recent = [list(d)[-20:] for n, d in self.ping_hist.items() if n != "Router"]
            jit_vals = []
            for d in recent:
                v = [r for _, r in d if r is not None]
                jit_vals += [abs(a - b) for a, b in zip(v, v[1:])]
            wifi = dict(self.wifi) if self.wifi else None
            events = list(self.recent_events)[:8]
            s = dict(self.session)
            down, up = self.last_bw
        sys_dns = [x for x in self.dns.values() if x["system"]]
        dns_ms = None
        if sys_dns:
            vals = [v for _, v in list(sys_dns[0]["hist"])[-10:] if v is not None]
            dns_ms = _avg(vals)
        devs = self.device_list()
        svcs = [v for v in self.services.values()]
        snap = {
            "now": now, "version": VERSION,
            "status": self.status(), "internet_up": self.internet_up,
            "latency": _avg(ext), "jitter": _avg(jit_vals), "loss": self.loss_pct(),
            "router": next((t["last"] for t in targets if t["name"] == "Router"), None),
            "targets": targets, "lat_series": lat_series, "bw_series": bw,
            "down": down, "up": up, "session": s,
            "uptime": 100 * s["up"] / s["samples"] if s["samples"] else None,
            "net": self.net, "public": self.public, "wifi": wifi, "dns_ms": dns_ms,
            "devices": {"online": sum(1 for d in devs if d["online"]), "known": len(devs),
                        "new": sum(1 for d in devs if d["is_new"]), "scan": dict(self.scan),
                        "types": _count([d["display_type"] for d in devs if d["online"]])},
            "services": {"total": len(svcs), "up": sum(1 for v in svcs if v.get("ok")),
                         "down": sum(1 for v in svcs if v.get("ok") is False)},
            "speed": {k: v for k, v in self.speed.items() if k != "live"},
            "plan": {"down": self.settings.get("plan_down_mbps"), "up": self.settings.get("plan_up_mbps")},
            "events": events, "alerts_paused": self.alerts_paused(),
            "paused_until": self.settings.get("alerts_paused_until", 0),
            "admin": winapi.is_admin(), "theme": self.settings.get("theme", "dark"),
        }
        try:
            snap["extra"] = self.extras.snap_extra(snap)
        except Exception:
            self.log_error("snap_extra")
            snap["extra"] = {}
        return snap


def _count(items):
    out = {}
    for i in items:
        out[i] = out.get(i, 0) + 1
    return out


def fmt_duration(seconds):
    seconds = int(max(0, seconds))
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m, s = divmod(rem, 60)
    if d:
        return f"{d}d {h}h"
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {s}s"
    return f"{s}s"
