"""NetWatch 3 feature manager: background workers and on-demand jobs for the v3 features, layered on the engine."""

import csv
import html
import socket
import statistics
import sys
import threading
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import diag, integrations, netops, security, winapi
from .engine import VERSION, fmt_duration

try:
    import psutil
except ImportError:
    psutil = None

EXTRA_DEFAULTS = {
    "quiet_enabled": False, "quiet_start": "22:30", "quiet_end": "07:00",
    "geo_enabled": False,
    "data_cap_gb": 0, "billing_day": 1,
    "anomaly_alerts": True, "new_app_alerts": True, "weekly_summary": False,
    "cloud_custom": [],
    "mqtt_enabled": False, "mqtt_host": "", "mqtt_port": 1883, "mqtt_user": "", "mqtt_password": "",
    "mqtt_discovery_prefix": "homeassistant", "mqtt_publish_devices": True,
    "dnsfilter_type": "pihole", "dnsfilter_url": "", "dnsfilter_user": "", "dnsfilter_password": "",
    "snmp_community": "public",
    "ai_key": "", "ai_model": "claude-sonnet-5-5",
    "update_repo": "", "auto_update_check": True, "onboarded": False, "last_version_seen": "",
    "site_role": "standalone", "site_name": socket.gethostname(), "hub_url": "", "site_key": "",
    "lan_enabled": False, "lan_port": 8780, "lan_pin": "",
    "downtime_cost_per_hour": 0, "overlay_on_start": False,
    "isp_counts": {}, "gateway_mac": "", "usage_alerted": "", "weekly_last": "", "update_notified": "",
    "survey": [],
}
SECRET_FIELDS = ("mqtt_password", "dnsfilter_password", "ai_key", "lan_pin")


def _hm(s):
    try:
        h, m = s.split(":")
        return int(h) * 60 + int(m)
    except (ValueError, AttributeError):
        return None


class Extras:
    def __init__(self, engine):
        self.e = engine
        for k, v in EXTRA_DEFAULTS.items():
            engine.settings.setdefault(k, v)
        from .version import UPDATE_REPO_DEFAULT
        if UPDATE_REPO_DEFAULT and not engine.settings.get("update_repo"):
            engine.settings["update_repo"] = UPDATE_REPO_DEFAULT
        self.pool = ThreadPoolExecutor(max_workers=8)
        self.capture = security.Capture(engine.data_dir / "captures")
        self.ha = integrations.HomeAssistantBridge(lambda: engine.settings)
        self.dnsfilter = integrations.DnsFilter(lambda: engine.settings)
        self.updater = integrations.Updater(engine.data_dir, VERSION)
        self.jobs = {}
        self.vpn = []
        self.captive = None
        self._last_ssid = None
        self._open_warned = set()
        self.spoof = {"shared_with": [], "gateway_mac": engine.settings.get("gateway_mac") or None, "flag": False}
        self.app_domains = defaultdict(dict)
        self.app_ips = defaultdict(set)
        self.app_paths = {}
        self.tracker_hits = defaultdict(int)
        self.geo = {}
        self._pid_exe = {}
        self.known = {a["path"] for a in engine.store.known_apps()}
        self._app_baseline = not self.known
        self.failover_id = None
        self._anomaly_last = {}
        self.certs = {}
        self._cert_warned = {}
        self.site = {"last_push": 0, "error": None}
        self.lan_state = {"running": False, "url": None, "error": None}
        self.ui_hooks = {}  # set by netwatch.py: toggle_overlay etc.
        self._last_presence = {}

    # ------------------------------------------------------------------ lifecycle
    def start(self):
        e = self.e
        jobs = [
            (lambda: 120, self._presence_tick, 25),
            (lambda: 300, self._anomaly_tick, 900),
            (lambda: 15, self._vpn_tick, 5),
            (lambda: 30, self._apps_tick, 12),
            (lambda: 15, self._captive_tick, 20),
            (lambda: 600, self._failover_tick, 120),
            (lambda: 30, self._mqtt_tick, 15),
            (lambda: 60, self._site_tick, 30),
            (lambda: 600, self._weekly_tick, 180),
            (lambda: 6 * 3600, self._update_tick, 300),
            (lambda: 900, self._usage_tick, 90),
            (lambda: 6 * 3600, self._cert_tick, 150),
        ]
        for interval, fn, delay in jobs:
            threading.Thread(target=e._loop, args=(interval, fn, delay), daemon=True).start()

    def stop(self):
        self.ha.stop()

    # ------------------------------------------------------------------ jobs (on-demand, long running)
    def run_job(self, name, fn, *args):
        j = self.jobs.get(name)
        if j and j.get("running"):
            return False
        self.jobs[name] = {"running": True, "started": time.time(), "result": None, "error": None}

        def work():
            try:
                self.jobs[name]["result"] = fn(*args)
            except Exception as ex:
                self.e.log_error(f"job {name}")
                self.jobs[name]["error"] = str(ex)
            finally:
                self.jobs[name]["running"] = False
                self.jobs[name]["finished"] = time.time()
        threading.Thread(target=work, daemon=True).start()
        return True

    def job(self, name):
        return self.jobs.get(name) or {"running": False, "result": None, "error": None}

    # ------------------------------------------------------------------ quiet hours
    def in_quiet_hours(self):
        s = self.e.settings
        if not s.get("quiet_enabled"):
            return False
        a, b = _hm(s.get("quiet_start")), _hm(s.get("quiet_end"))
        if a is None or b is None:
            return False
        now = datetime.now()
        m = now.hour * 60 + now.minute
        return (a <= m < b) if a < b else (m >= a or m < b)

    def allow_notification(self, level, category):
        if not self.in_quiet_hours():
            return True
        return level == "ALERT" and category in ("internet", "security")

    # ------------------------------------------------------------------ presence & spoofing
    def _presence_tick(self):
        e = self.e
        now = time.time()
        with e.lock:
            devs = {k: dict(d) for k, d in e.devices.items()}
        targets = {k: d["ip"] for k, d in devs.items() if d.get("ip") and now - (d.get("last_seen") or 0) < 30 * 86400}
        with ThreadPoolExecutor(max_workers=48) as pool:
            rtts = dict(zip(targets, pool.map(lambda ip: winapi.ping(ip, 600), targets.values())))
        arp = netops.read_arp_table()
        mac_ip = {m: ip for ip, m in arp.items()}
        online = {}
        for k, d in devs.items():
            if d.get("self"):
                online[k] = {"rtt": 0.0}
                continue
            if rtts.get(k) is not None:
                online[k] = {"rtt": rtts[k]}
            elif d.get("mac") and d["mac"] in mac_ip and k in targets:
                online[k] = {"rtt": None}
        with e.lock:
            for k in online:
                if k in e.devices:
                    e.devices[k]["last_seen"] = now
                    m = e.devices[k].get("mac")
                    if m and m in mac_ip and mac_ip[m] != e.devices[k].get("ip"):
                        e.devices[k]["ip"] = mac_ip[m]
            if not e.scan["running"]:
                e.online = online
        e.store.add_presence(now, list(online))
        # untrusted known devices returning after a long absence
        for k in online:
            d = devs.get(k, {})
            prev = self._last_presence.get(k, d.get("last_seen") or now)
            if not d.get("trusted") and not d.get("self") and not d.get("gateway") and now - prev > 86400 \
                    and d.get("first_seen", now) < now - 86400:
                label = d.get("name") or d.get("hostname") or d.get("ip")
                e.event("INFO", "device", f"Untrusted device back online after {fmt_duration(now - prev)}: {label}")
        for k in online:
            self._last_presence[k] = now
        # ARP spoofing / router change
        gw = e.net.get("gateway")
        chk = security.arp_spoof_check(arp, gw)
        gmac = chk["gateway_mac"]
        stored = e.settings.get("gateway_mac")
        if gmac:
            if chk["shared_with"] and not self.spoof["flag"]:
                self.spoof["flag"] = True
                e.event("ALERT", "security", f"Possible ARP spoofing: your router's hardware address ({gmac}) is also "
                        f"claimed by {', '.join(chk['shared_with'])}. Someone may be intercepting traffic.", notify=True)
            elif not chk["shared_with"]:
                self.spoof["flag"] = False
            if stored and stored != gmac:
                e.event("WARN", "security", f"Your router's hardware address changed ({stored} → {gmac}). Expected if "
                        f"you replaced the router; otherwise it could indicate spoofing.", notify=True)
            if stored != gmac:
                e.save_settings({"gateway_mac": gmac})
        self.spoof.update(shared_with=chk["shared_with"], gateway_mac=gmac)

    def timeline(self, hours=24):
        since = time.time() - hours * 3600
        rows = self.e.store.presence(since)
        by = defaultdict(list)
        for ts, k in rows:
            by[k].append(ts)
        devs = self.e.device_list()
        out = []
        for d in devs:
            pts = by.get(d["key"], [])
            if not pts and not d["online"]:
                continue
            out.append({"key": d["key"], "name": d.get("name") or d.get("hostname") or d.get("vendor_short") or d["ip"],
                        "type": d["display_type"], "online": d["online"], "trusted": bool(d.get("trusted")),
                        "points": pts})
        out.sort(key=lambda x: (-len(x["points"]), x["name"].lower()))
        return {"since": since, "until": time.time(), "interval": 120, "devices": out}

    def overnight(self):
        now = datetime.now()
        night = now.replace(hour=1, minute=0, second=0, microsecond=0)
        if now.hour < 5:
            night -= timedelta(days=1)
        t0, t1 = night.timestamp(), (night + timedelta(hours=4)).timestamp()
        rows = [r for r in self.e.store.presence(t0) if r[0] < t1]
        ticks = len({int(ts // 120) for ts, _ in rows}) or 1
        count = defaultdict(int)
        for ts, k in rows:
            count[k] += 1
        devs = {d["key"]: d for d in self.e.device_list()}
        awake = []
        for k, c in count.items():
            d = devs.get(k)
            if not d or d.get("self") or d.get("gateway"):
                continue
            awake.append({"key": k, "name": d.get("name") or d.get("hostname") or d.get("vendor_short") or d["ip"],
                          "type": d["display_type"], "pct": round(100 * c / ticks)})
        awake.sort(key=lambda x: -x["pct"])
        mins = [r for r in self.e.store.export_minutes(30) if t0 <= r[0] < t1]
        traffic = sum((r[7] or 0) * 60 + (r[8] or 0) * 60 for r in mins)
        return {"window": [t0, t1], "devices": awake, "pc_traffic": traffic,
                "monitored": bool(rows or mins), "ticks": ticks}

    # ------------------------------------------------------------------ anomalies
    def _anomaly_tick(self):
        e = self.e
        if not e.settings.get("anomaly_alerts") or not e.internet_up:
            return
        recent = e.store.recent_minutes(10)
        lat = [r[2] for r in recent if r[2] is not None]
        if len(lat) < 6:
            return
        base = e.store.latency_baseline(datetime.now().hour)
        if len(base) < 300:
            return
        bl = [r[0] for r in base]
        med = statistics.median(bl)
        mad = statistics.median(abs(x - med) for x in bl) or 1
        cur = statistics.median(lat)
        now = time.time()
        if cur > med + max(4 * 1.4826 * mad, 20) and cur > med * 1.6 and now - self._anomaly_last.get("lat", 0) > 3600:
            self._anomaly_last["lat"] = now
            e.event("WARN", "latency", f"Latency is unusually high for this time of day: {cur:.0f} ms vs a normal "
                    f"{med:.0f} ms", notify=True)
        bloss = statistics.mean(r[1] or 0 for r in base)
        closs = statistics.mean(r[3] or 0 for r in recent)
        if closs > max(2, 4 * bloss) and now - self._anomaly_last.get("loss", 0) > 3600:
            self._anomaly_last["loss"] = now
            e.event("WARN", "loss", f"Packet loss is unusually high: {closs:.1f}% vs a normal {bloss:.2f}%", notify=True)
        bdns = [r[2] for r in base if r[2] is not None]
        cdns = [r[6] for r in recent if r[6] is not None]
        if len(bdns) > 100 and cdns:
            dm, cd = statistics.median(bdns), statistics.median(cdns)
            if cd > max(dm * 3, dm + 60) and now - self._anomaly_last.get("dns", 0) > 3600:
                self._anomaly_last["dns"] = now
                e.event("WARN", "dns", f"DNS lookups are unusually slow: {cd:.0f} ms vs a normal {dm:.0f} ms", notify=True)

    # ------------------------------------------------------------------ VPN & captive portal
    def _vpn_tick(self):
        cur = diag.vpn_adapters()
        up = sorted(a["name"] for a in cur if a["up"])
        prev = sorted(a["name"] for a in self.vpn if a["up"]) if self.vpn else None
        self.vpn = cur
        if prev is None:
            return
        for n in set(up) - set(prev):
            self.e.event("INFO", "security", f"VPN connected ({n})")
        for n in set(prev) - set(up):
            self.e.event("WARN", "security", f"VPN disconnected ({n}) - your traffic is no longer going through the VPN",
                         notify=True)

    def vpn_up(self):
        return any(a["up"] for a in self.vpn)

    def _captive_tick(self):
        w = self.e.wifi
        if not w or w.get("error") or not w.get("connected"):
            self._last_ssid = None
            return
        ssid = w.get("ssid")
        changed = ssid != self._last_ssid
        due = not self.captive or time.time() - self.captive.get("ts", 0) > 600
        if not (changed or due):
            return
        self._last_ssid = ssid
        if "open" in (w.get("auth") or "").lower() and ssid not in self._open_warned:
            self._open_warned.add(ssid)
            self.e.event("WARN", "security", f"Connected to an open (unencrypted) Wi-Fi network: {ssid}. Avoid "
                         f"sensitive sites or use a VPN.", notify=True, remote=False)
        r = security.captive_portal_check()
        r["ts"] = time.time()
        r["ssid"] = ssid
        was = (self.captive or {}).get("portal")
        self.captive = r
        if r.get("portal") and not was:
            self.e.event("WARN", "security", f"{ssid} needs you to sign in on a web page (captive portal) before the "
                         f"internet works.", notify=True, remote=False)

    # ------------------------------------------------------------------ failover detection
    def _failover_tick(self):
        e = self.e
        pub = e.public or {}
        isp = (pub.get("isp") or "").strip()
        if not isp or self.vpn_up():
            return
        counts = dict(e.settings.get("isp_counts") or {})
        counts[isp] = counts.get(isp, 0) + 1
        e.save_settings({"isp_counts": counts})
        primary = max(counts, key=counts.get)
        if counts[primary] < 6:
            return
        if isp != primary and not self.failover_id:
            self.failover_id = e.store.start_failover(time.time(), isp)
            e.event("WARN", "internet", f"Switched to a backup connection ({isp}) - your main ISP ({primary}) may be down",
                    notify=True)
        elif isp == primary and self.failover_id:
            e.store.end_failover(self.failover_id, time.time())
            self.failover_id = None
            e.event("OK", "internet", f"Back on your main connection ({primary})")

    # ------------------------------------------------------------------ apps: new apps, domains, geo
    def _exe(self, pid):
        if pid in self._pid_exe:
            return self._pid_exe[pid]
        try:
            p = psutil.Process(pid)
            v = (p.exe() or "", p.name())
        except Exception:
            v = ("", f"PID {pid}")
        self._pid_exe[pid] = v
        return v

    def _apps_tick(self):
        if psutil is None:
            return
        e = self.e
        now = time.time()
        try:
            conns = psutil.net_connections(kind="inet")
        except Exception:
            return
        cache = diag.dns_cache_map() if winapi.IS_WINDOWS else {}
        new_paths = []
        for c in conns:
            if not c.raddr or not c.pid:
                continue
            path, name = self._exe(c.pid)
            if path:
                self.app_paths[name] = path
                if path not in self.known:
                    self.known.add(path)
                    e.store.add_known_app(path, name, now)
                    new_paths.append((path, name))
            ip = c.raddr.ip
            if len(self.app_ips[name]) < 300:
                self.app_ips[name].add(ip)
            dom = cache.get(ip)
            if dom:
                d = self.app_domains[name].setdefault(dom, {"count": 0, "first": now, "last": now,
                                                            "tracker": diag.is_tracker(dom)})
                d["count"] += 1
                d["last"] = now
                if d["tracker"]:
                    self.tracker_hits[name] += 1
        if len(self._pid_exe) > 3000:
            self._pid_exe.clear()
        if self._app_baseline:
            self._app_baseline = False
        else:
            for path, name in new_paths:
                self.pool.submit(self._check_new_app, path, name)
        if e.settings.get("geo_enabled"):
            ips = {ip for s in self.app_ips.values() for ip in s if ip not in self.geo and diag._is_public(ip)}
            if ips:
                cached = e.store.geo_get(list(ips))
                self.geo.update(cached)
                missing = [ip for ip in ips if ip not in cached][:100]
                if missing:
                    try:
                        got = diag.geo_batch(missing)
                        self.geo.update(got)
                        e.store.geo_put(got)
                        for ip in missing:
                            self.geo.setdefault(ip, None)
                    except Exception:
                        pass

    def _check_new_app(self, path, name):
        sig = security.signature(path)
        self.e.store.update_app(path, signed=sig["status"], publisher=sig["publisher"])
        if not self.e.settings.get("new_app_alerts"):
            return
        if sig["status"] == "signed":
            self.e.event("INFO", "security", f"New app using the internet: {name}" +
                         (f" ({sig['publisher']})" if sig["publisher"] else ""))
        else:
            self.e.event("WARN", "security", f"New {'unsigned ' if sig['status'] == 'unsigned' else ''}app using the "
                         f"internet: {name} ({path})", notify=True, remote=False)

    def apps_security(self):
        apps = self.e.store.known_apps()
        blocked = {a["path"] for a in apps if a.get("blocked")}
        doms = {}
        for app, ds in self.app_domains.items():
            items = sorted(ds.items(), key=lambda kv: -kv[1]["last"])[:60]
            doms[app] = [{"domain": k, "base": diag.base_domain(k), **v} for k, v in items]
        return {"apps": apps[:300], "blocked": sorted(blocked), "domains": doms,
                "trackers": dict(self.tracker_hits), "paths": self.app_paths, "admin": winapi.is_admin(),
                "dns_cache_supported": winapi.IS_WINDOWS}

    def world(self):
        pts = defaultdict(lambda: {"apps": set(), "ips": set()})
        for app, ips in self.app_ips.items():
            for ip in ips:
                g = self.geo.get(ip)
                if not g or g.get("lat") is None:
                    continue
                key = (round(g["lat"], 1), round(g["lon"], 1))
                p = pts[key]
                p.update(lat=g["lat"], lon=g["lon"], city=g.get("city"), country=g.get("country"), cc=g.get("cc"),
                         org=g.get("org") or g.get("isp"))
                p["apps"].add(app)
                p["ips"].add(ip)
        out = [{**{k: v for k, v in p.items() if k not in ("apps", "ips")}, "apps": sorted(p["apps"])[:8],
                "count": len(p["ips"])} for p in pts.values()]
        countries = defaultdict(int)
        for p in out:
            countries[p.get("country") or "?"] += p["count"]
        home = (self.e.public or {}).get("country")
        return {"enabled": bool(self.e.settings.get("geo_enabled")), "points": out,
                "countries": sorted(countries.items(), key=lambda kv: -kv[1]), "home": home,
                "pending": sum(1 for s in self.app_ips.values() for ip in s if ip not in self.geo)}

    def block_app(self, path, block=True):
        if block:
            security.block_app(path)
            self.e.store.update_app(path, blocked=1)
            self.e.event("INFO", "security", f"Blocked internet access for {path}")
        else:
            security.unblock_app(path)
            self.e.store.update_app(path, blocked=0)
            self.e.event("INFO", "security", f"Unblocked internet access for {path}")
        return True

    # ------------------------------------------------------------------ MQTT / sites / weekly / updates / usage / certs
    def _mqtt_tick(self):
        s = self.e.settings
        if not s.get("mqtt_enabled") or not s.get("mqtt_host"):
            return
        snap = self.e.snapshot()
        q = diag.quality(snap.get("latency"), snap.get("jitter"), snap.get("loss")) or {}
        sp = (snap.get("speed") or {}).get("result") or {}
        w = snap.get("wifi") or {}
        r2 = lambda v, n=1: None if v is None else round(v, n)
        values = {"internet": bool(snap.get("internet_up")), "latency": r2(snap.get("latency")),
                  "jitter": r2(snap.get("jitter")), "loss": r2(snap.get("loss"), 2),
                  "download": r2((snap.get("down") or 0) * 8 / 1e6, 2), "upload": r2((snap.get("up") or 0) * 8 / 1e6, 2),
                  "devices_online": snap["devices"]["online"], "wifi_signal": w.get("signal"),
                  "dns_ms": r2(snap.get("dns_ms")), "speed_down": sp.get("down"), "speed_up": sp.get("up"),
                  "call_quality": q.get("mos"), "status": snap["status"]["title"],
                  "public_ip": (snap.get("public") or {}).get("ip")}
        presence = {}
        if s.get("mqtt_publish_devices"):
            for d in self.e.device_list():
                if d.get("name") and not d.get("self"):
                    presence[d["key"]] = (d["name"], d["online"])
        self.ha.publish(values, presence)

    def site_report(self):
        snap = self.e.snapshot()
        sp = (snap.get("speed") or {}).get("result") or {}
        return {"name": self.e.settings.get("site_name") or socket.gethostname(), "version": VERSION,
                "ts": time.time(), "status": snap["status"], "internet_up": snap.get("internet_up"),
                "latency": snap.get("latency"), "loss": snap.get("loss"), "jitter": snap.get("jitter"),
                "down": snap.get("down"), "up": snap.get("up"), "uptime": snap.get("uptime"),
                "public": snap.get("public"), "devices": {"online": snap["devices"]["online"],
                                                          "known": snap["devices"]["known"]},
                "speed": {"down": sp.get("down"), "up": sp.get("up"), "ts": sp.get("ts")},
                "events": snap.get("events", [])[:5], "services": snap.get("services")}

    def _site_tick(self):
        s = self.e.settings
        if s.get("site_role") != "agent" or not s.get("hub_url") or not s.get("site_key"):
            return
        try:
            integrations.push_site_report(s["hub_url"], s["site_key"], self.site_report())
            self.site = {"last_push": time.time(), "error": None}
        except Exception as ex:
            self.site = {"last_push": self.site.get("last_push", 0), "error": str(ex)}

    def receive_site(self, report, key):
        s = self.e.settings
        if s.get("site_role") != "hub" or not s.get("site_key") or key != s["site_key"]:
            return False
        name = str(report.get("name") or "unknown")[:60]
        prev = {x["name"]: x for x in self.e.store.sites()}.get(name)
        self.e.store.put_site(name, report)
        if prev and prev.get("internet_up") and report.get("internet_up") is False:
            self.e.event("ALERT", "internet", f"Site '{name}' has lost its internet connection", notify=True)
        return True

    def sites_view(self):
        sites = self.e.store.sites()
        now = time.time()
        for x in sites:
            x["stale"] = now - x["last_seen"] > 300
        me = self.site_report()
        me["local"] = True
        return {"role": self.e.settings.get("site_role"), "sites": sites, "self": me, "push": self.site}

    def _weekly_tick(self):
        s = self.e.settings
        now = datetime.now()
        week = now.strftime("%G-W%V")
        if not s.get("weekly_summary") or now.weekday() != 0 or now.hour < 8 or s.get("weekly_last") == week:
            return
        self.e.save_settings({"weekly_last": week})
        self.e.remote.send("INFO", "Weekly summary", self.weekly_text(), force=True)

    def weekly_text(self):
        h = self.e.store.history(168)
        s = h["summary"]
        u = self.usage()
        devs = self.e.device_list()
        new = [d for d in devs if d.get("first_seen", 0) > time.time() - 7 * 86400]
        lines = [f"Your network over the last 7 days:",
                 f"• Uptime: {s['uptime']:.2f}%" if s["uptime"] is not None else "• Uptime: not enough data",
                 f"• Outages: {s['outages']} ({fmt_duration(s['outage_s'])} offline)",
                 f"• Average latency: {s['latency']:.0f} ms, packet loss {s['loss']:.2f}%" if s["latency"] else "",
                 f"• Average speed: {s['avg_speed_down']:.0f} / {s['avg_speed_up']:.0f} Mbps"
                 if s["avg_speed_down"] else "• No speed tests this week",
                 f"• Data used: {u['week_bytes'] / 1e9:.1f} GB",
                 f"• New devices: {len(new)}" + (f" ({', '.join(d.get('name') or d.get('hostname') or d['ip'] for d in new[:6])})"
                                                  if new else "")]
        return "\n".join(x for x in lines if x)

    def _update_tick(self):
        s = self.e.settings
        if not s.get("update_repo") or not s.get("auto_update_check"):
            return
        st = self.updater.check(s["update_repo"])
        if st.get("available") and s.get("update_notified") != st["latest"]:
            self.e.save_settings({"update_notified": st["latest"]})
            self.e.event("INFO", "app", f"NetWatch {st['latest']} is available - open Settings to install it", notify=True,
                         remote=False)

    def usage(self):
        s = self.e.settings
        now = datetime.now()
        bday = max(1, min(28, int(s.get("billing_day") or 1)))
        start = now.replace(day=bday, hour=0, minute=0, second=0, microsecond=0)
        if now.day < bday:
            start = (start - timedelta(days=1)).replace(day=bday)
        nxt = (start + timedelta(days=32)).replace(day=bday)
        days = self.e.store.usage_by_day(int(time.time()) - 62 * 86400)
        cyc = [d for d in days if d["date"] >= start.strftime("%Y-%m-%d")]
        mtd = sum(d["down"] + d["up"] for d in cyc)
        elapsed = max(0.5, (now - start).total_seconds() / 86400)
        length = (nxt - start).days
        week_since = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        cap = float(s.get("data_cap_gb") or 0) * 1e9
        return {"days": days[-60:], "cycle_start": start.timestamp(), "cycle_end": nxt.timestamp(),
                "mtd": mtd, "projected": mtd / elapsed * length, "cap": cap or None,
                "pct": 100 * mtd / cap if cap else None,
                "week_bytes": sum(d["down"] + d["up"] for d in days if d["date"] >= week_since),
                "today": next((d for d in days if d["date"] == now.strftime("%Y-%m-%d")), None),
                "note": "Counts traffic through this PC while NetWatch is running."}

    def _usage_tick(self):
        u = self.usage()
        if not u["cap"]:
            return
        cycle = datetime.fromtimestamp(u["cycle_start"]).strftime("%Y-%m-%d")
        done = self.e.settings.get("usage_alerted") or ""
        for level in (100, 80):
            key = f"{cycle}:{level}"
            if u["pct"] >= level and not done.startswith(key) and not (level == 80 and done.startswith(f"{cycle}:100")):
                self.e.save_settings({"usage_alerted": key})
                self.e.event("WARN", "network", f"You've used {u['pct']:.0f}% of your {u['cap'] / 1e9:.0f} GB data "
                             f"allowance this cycle", notify=True)
                break

    def _cert_tick(self):
        for c in self.e.settings.get("services", []):
            if c.get("type") != "http" or not c.get("enabled", True) or not c.get("target", "").startswith("https"):
                continue
            try:
                info = diag.cert_expiry(c["target"])
            except Exception as ex:
                self.certs[c["id"]] = {"error": str(ex)[:80]}
                continue
            self.certs[c["id"]] = info
            if info["days"] <= 14 and time.time() - self._cert_warned.get(c["id"], 0) > 86400:
                self._cert_warned[c["id"]] = time.time()
                self.e.event("WARN", "service", f"The security certificate for {c['name']} expires in {info['days']} "
                             f"day(s)", notify=True)

    # ------------------------------------------------------------------ Wi-Fi survey & roaming
    def survey_record(self, room):
        room = (room or "").strip()[:40]
        if not room:
            raise ValueError("Enter a room name")
        sig, rx, lat = [], [], []
        gw = self.e.net.get("gateway")
        for _ in range(8):
            w = netops.wifi_status() if winapi.IS_WINDOWS else self.e.wifi
            if w and not w.get("error") and w.get("signal") is not None:
                sig.append(w["signal"])
                if w.get("rx_rate"):
                    rx.append(w["rx_rate"])
            if gw:
                r = winapi.ping(gw, 600)
                if r is not None:
                    lat.append(r)
            time.sleep(1)
        if not sig:
            raise RuntimeError("Couldn't read the Wi-Fi signal - is this PC on Wi-Fi?")
        w = self.e.wifi or {}
        rec = {"room": room, "signal": round(statistics.mean(sig)), "min": min(sig), "max": max(sig),
               "rx_rate": round(statistics.mean(rx)) if rx else None,
               "router_ms": round(statistics.mean(lat), 1) if lat else None,
               "bssid": w.get("bssid"), "band": w.get("band"), "channel": w.get("channel"), "ts": time.time()}
        survey = [r for r in self.e.settings.get("survey", []) if r["room"].lower() != room.lower()] + [rec]
        self.e.save_settings({"survey": survey})
        return rec

    def survey_delete(self, room):
        self.e.save_settings({"survey": [r for r in self.e.settings.get("survey", []) if r["room"] != room]})

    def on_wifi(self, prev, info):
        """Called by the engine on every Wi-Fi sample."""
        if not info or info.get("error") or not info.get("connected") or not info.get("bssid"):
            return
        self.e.store.touch_ap(info["bssid"], info.get("ssid"), info.get("channel") if isinstance(info.get("channel"), int)
                              else None, info.get("band"), info.get("signal"), time.time())
        if prev and not prev.get("error") and prev.get("connected") and prev.get("bssid") and \
                prev["bssid"] != info["bssid"]:
            self.e.store.add_roam(time.time(), info.get("ssid"), prev["bssid"], info["bssid"],
                                  info.get("channel") if isinstance(info.get("channel"), int) else None, info.get("signal"))

    def mesh_view(self):
        aps = self.e.store.aps()
        roams = self.e.store.roams(time.time() - 7 * 86400)
        cur = (self.e.wifi or {}).get("bssid")
        for a in aps:
            a["current"] = a["bssid"] == cur
        return {"aps": aps, "roams": roams, "current": cur}

    # ------------------------------------------------------------------ inventory export
    def inventory_rows(self):
        rows = []
        for d in sorted(self.e.device_list(), key=lambda x: [int(p) for p in (x.get("ip") or "0.0.0.0").split(".")]):
            rows.append([d.get("name") or "", d.get("display_type", ""), d.get("ip", ""), d.get("mac", ""),
                         d.get("vendor", ""), d.get("hostname", ""), "Yes" if d["online"] else "No",
                         "Yes" if d.get("trusted") else "No",
                         ", ".join(f"{p['port']} {p['service']}".strip() for p in (d.get("ports") or [])),
                         datetime.fromtimestamp(d.get("first_seen") or 0).strftime("%Y-%m-%d %H:%M"),
                         datetime.fromtimestamp(d.get("last_seen") or 0).strftime("%Y-%m-%d %H:%M"),
                         d.get("notes", "")])
        return ["Name", "Type", "IP address", "MAC address", "Manufacturer", "Hostname", "Online", "Trusted",
                "Open ports", "First seen", "Last seen", "Notes"], rows

    def export_inventory(self, path):
        head, rows = self.inventory_rows()
        if path.lower().endswith(".xlsx"):
            try:
                from openpyxl import Workbook
                from openpyxl.styles import Font, PatternFill
                from openpyxl.worksheet.table import Table, TableStyleInfo
            except ImportError:
                path = path[:-5] + ".csv"
            else:
                wb = Workbook()
                ws = wb.active
                ws.title = "Devices"
                ws.append(head)
                for r in rows:
                    ws.append(r)
                for c in ws[1]:
                    c.font = Font(bold=True, color="FFFFFF")
                    c.fill = PatternFill("solid", fgColor="1E293B")
                widths = [22, 14, 15, 19, 30, 24, 8, 8, 34, 17, 17, 30]
                for i, w in enumerate(widths):
                    ws.column_dimensions[chr(65 + i)].width = w
                if rows:
                    t = Table(displayName="Devices", ref=f"A1:{chr(64 + len(head))}{len(rows) + 1}")
                    t.tableStyleInfo = TableStyleInfo(name="TableStyleMedium2", showRowStripes=True)
                    ws.add_table(t)
                ws.freeze_panes = "A2"
                wb.save(path)
                return path
        if path.lower().endswith(".html"):
            esc = html.escape
            body = "".join("<tr>" + "".join(f"<td>{esc(str(c))}</td>" for c in r) + "</tr>" for r in rows)
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(f"""<!doctype html><html><head><meta charset="utf-8"><title>Network inventory</title><style>
body{{font-family:Segoe UI,system-ui,sans-serif;margin:28px;color:#0f172a}}table{{border-collapse:collapse;width:100%;font-size:12px}}
th,td{{border-bottom:1px solid #e2e8f0;padding:6px 8px;text-align:left}}th{{background:#f1f5f9}}h1{{font-size:22px;margin:0}}
.m{{color:#64748b;margin:4px 0 18px}}@page{{size:landscape}}</style></head><body><h1>Network inventory</h1>
<div class="m">{len(rows)} devices · {esc(self.e.net.get('network') or '')} · generated {datetime.now():%d %B %Y %H:%M} by NetWatch</div>
<table><tr>{''.join(f'<th>{esc(h)}</th>' for h in head)}</tr>{body}</table></body></html>""")
            return path
        with open(path, "w", newline="", encoding="utf-8") as fh:
            w = csv.writer(fh)
            w.writerow(head)
            w.writerows(rows)
        return path

    # ------------------------------------------------------------------ security overview
    def security_view(self):
        pc = (self.job("pc").get("result") or {})
        upnp = self.job("upnp").get("result")
        exp = self.job("exposure").get("result")
        dhcp = self.job("dhcp").get("result")
        devs = self.e.device_list()
        untrusted = [d for d in devs if d["online"] and not d.get("trusted") and not d.get("self")]
        issues = []
        if self.spoof.get("shared_with"):
            issues.append(("bad", "Possible ARP spoofing detected"))
        if dhcp and dhcp.get("rogue"):
            issues.append(("bad", "More than one DHCP server answered"))
        if upnp and upnp.get("mappings"):
            r = [m for m in upnp["mappings"] if m.get("risky")]
            issues.append(("bad" if r else "warn", f"{len(upnp['mappings'])} port forward(s) open on your router"))
        if exp and exp.get("ports"):
            issues.append(("bad" if exp.get("vulns") else "warn", f"{len(exp['ports'])} port(s) visible from the internet"))
        if pc.get("score") is not None and pc["score"] < 80:
            issues.append(("warn", "This PC has security settings to review"))
        if untrusted:
            issues.append(("info", f"{len(untrusted)} online device(s) not marked as trusted"))
        if self.captive and self.captive.get("portal"):
            issues.append(("warn", "Captive portal intercepting traffic"))
        w = self.e.wifi or {}
        if w.get("connected") and "open" in (w.get("auth") or "").lower():
            issues.append(("bad", "Connected to an open Wi-Fi network"))
        pen = {"bad": 20, "warn": 8, "info": 2}
        score = max(0, 100 - sum(pen[i[0]] for i in issues))
        return {"score": score, "issues": [{"level": l, "text": t} for l, t in issues],
                "pc": pc, "pc_job": self.job("pc"), "upnp": upnp, "upnp_job": self.job("upnp"),
                "exposure": exp, "exposure_job": self.job("exposure"), "dhcp": dhcp, "dhcp_job": self.job("dhcp"),
                "spoof": self.spoof, "vpn": self.vpn, "leak": self.job("leak"), "captive": self.captive,
                "wifi_auth": w.get("auth"), "wifi_ssid": w.get("ssid"),
                "untrusted": [{"key": d["key"], "name": d.get("name") or d.get("hostname") or d.get("vendor_short") or d["ip"],
                               "ip": d["ip"], "type": d["display_type"]} for d in untrusted],
                "capture": dict(self.capture.state), "admin": winapi.is_admin(), "windows": winapi.IS_WINDOWS,
                "public_ip": (self.e.public or {}).get("ip")}

    # ------------------------------------------------------------------ snapshot additions
    def snap_extra(self, snap):
        q = diag.quality(snap.get("latency"), snap.get("jitter"), snap.get("loss"),
                         ((snap.get("speed") or {}).get("result") or {}).get("down"))
        u = None
        try:
            if time.time() - getattr(self, "_usage_ts", 0) > 60:
                self._usage_cache = self.usage()
                self._usage_ts = time.time()
            u = self._usage_cache
        except Exception:
            pass
        devs_untrusted = sum(1 for d in self.e.device_list() if d["online"] and not d.get("trusted") and not d.get("self"))
        return {"quality": q, "vpn": [a for a in self.vpn if a["up"]], "captive": self.captive,
                "usage": {"mtd": u["mtd"], "cap": u["cap"], "pct": u["pct"], "today": (u["today"] or {})} if u else None,
                "untrusted_online": devs_untrusted, "failover": bool(self.failover_id),
                "spoof": bool(self.spoof.get("shared_with")), "quiet": self.in_quiet_hours(),
                "update": self.updater.state.get("latest") if self.updater.state.get("available") else None,
                "site_role": self.e.settings.get("site_role"), "lan": self.lan_state.get("url")}

    # ------------------------------------------------------------------ assistant context
    def assistant_context(self):
        e = self.e
        snap = e.snapshot()
        for k in ("lat_series", "bw_series"):
            snap.pop(k, None)
        h7 = e.store.history(168)
        h7.pop("series", None)
        devs = [{"name": d.get("name") or d.get("hostname"), "type": d["display_type"], "ip": d["ip"],
                 "vendor": d.get("vendor_short"), "online": d["online"], "new": d["is_new"],
                 "trusted": bool(d.get("trusted"))} for d in e.device_list()]
        return {"now": datetime.now().isoformat(timespec="minutes"), "current": snap, "last_7_days": h7,
                "outages_30_days": e.store.history(720)["outages"][:30], "events": e.store.events(60),
                "devices": devs, "wifi": e.wifi_view(), "dns": e.dns_view(),
                "services": [{k: v for k, v in s.items() if k != "hist"} for s in e.services_view()],
                "usage": {k: v for k, v in self.usage().items() if k != "days"},
                "settings": {"plan_down_mbps": e.settings.get("plan_down_mbps"),
                             "plan_up_mbps": e.settings.get("plan_up_mbps")}}
