"""Diagnostics: troubleshooter and fixes, call/gaming quality scores, bufferbloat grading, Microsoft 365 and
cloud latency tests, "is it just me?", IPv6 health, VPN detection & leak test, DNS cache domains, trackers, GeoIP."""

import ctypes
import ipaddress
import json
import re
import socket
import ssl
import statistics
import threading
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from . import netops, winapi
from .netops import USER_AGENT
from .winapi import IS_WINDOWS, run_cmd

try:
    import psutil
except ImportError:
    psutil = None


# --------------------------------------------------------------------------- #
# Quality scores
# --------------------------------------------------------------------------- #

def mos_score(latency, jitter, loss):
    """Simplified ITU-T G.107 E-model -> Mean Opinion Score (1-4.5)."""
    if latency is None:
        return None
    jitter = jitter or 0
    loss = loss or 0
    eff = latency + 2 * jitter + 10
    r = 93.2 - (eff / 40 if eff < 160 else (eff - 120) / 10) - 2.5 * loss
    r = max(0, min(100, r))
    return round(1 + 0.035 * r + 0.000007 * r * (r - 60) * (100 - r), 2)


def _rating(score):
    return "Excellent" if score >= 4.3 else "Good" if score >= 4.0 else "Fair" if score >= 3.6 else \
        "Poor" if score >= 3.1 else "Bad"


def quality(latency, jitter, loss, down_mbps=None):
    mos = mos_score(latency, jitter, loss)
    if mos is None:
        return None
    lat, jit, ls = latency, jitter or 0, loss or 0
    if lat < 30 and jit < 5 and ls < 0.5:
        gaming = "Excellent"
    elif lat < 60 and jit < 15 and ls < 1:
        gaming = "Good"
    elif lat < 100 and jit < 30 and ls < 2.5:
        gaming = "Fair"
    else:
        gaming = "Poor"
    stream = None
    if down_mbps is not None:
        stream = "4K" if down_mbps >= 25 else "HD" if down_mbps >= 5 else "SD" if down_mbps >= 3 else "Low"
    return {"mos": mos, "calls": _rating(mos), "gaming": gaming, "streaming": stream}


def bufferbloat_grade(idle, loaded):
    if idle is None or loaded is None:
        return None
    inc = max(0, loaded - idle)
    return "A+" if inc < 5 else "A" if inc < 30 else "B" if inc < 60 else "C" if inc < 200 else \
        "D" if inc < 400 else "F"


class LatencySampler:
    """Pings in the background (e.g. during a speed test) and buckets samples by phase."""

    def __init__(self, target="1.1.1.1", interval=0.25):
        self.target, self.interval = target, interval
        self.phase = "idle"
        self.samples = {}
        self._stop = threading.Event()
        self._t = None

    def start(self):
        self._t = threading.Thread(target=self._run, daemon=True)
        self._t.start()
        return self

    def _run(self):
        while not self._stop.is_set():
            rtt = winapi.ping(self.target, 800)
            if rtt is not None:
                self.samples.setdefault(self.phase, []).append(rtt)
            self._stop.wait(self.interval)

    def stop(self):
        self._stop.set()

    def median(self, phase):
        v = self.samples.get(phase) or []
        if len(v) < 3:
            return None
        v = sorted(v)
        return statistics.median(v[len(v) // 10: max(len(v) // 10 + 1, len(v) - len(v) // 20)])


# --------------------------------------------------------------------------- #
# Troubleshooter
# --------------------------------------------------------------------------- #

FIXES = {
    "flush_dns": {"title": "Flush DNS cache", "admin": False},
    "renew_ip": {"title": "Renew IP address", "admin": True},
    "reset_adapter": {"title": "Restart network adapter", "admin": True},
    "reset_winsock": {"title": "Reset network stack (needs reboot)", "admin": True},
    "use_public_dns": {"title": "Switch this PC to Cloudflare DNS", "admin": True},
}


def run_fix(fix_id, interface=None):
    if fix_id not in FIXES:
        raise ValueError("Unknown fix")
    if not IS_WINDOWS:
        raise RuntimeError("Fixes are available on Windows only")
    if FIXES[fix_id]["admin"] and not winapi.is_admin():
        raise RuntimeError("This fix needs administrator rights - restart NetWatch as administrator.")
    if fix_id == "flush_dns":
        out = run_cmd(["ipconfig", "/flushdns"])
    elif fix_id == "renew_ip":
        out = run_cmd(["ipconfig", "/renew"], timeout=60)
    elif fix_id == "reset_adapter":
        if not interface:
            raise RuntimeError("No active adapter found")
        run_cmd(["netsh", "interface", "set", "interface", f"name={interface}", "admin=disabled"])
        time.sleep(3)
        out = run_cmd(["netsh", "interface", "set", "interface", f"name={interface}", "admin=enabled"])
    elif fix_id == "reset_winsock":
        out = run_cmd(["netsh", "winsock", "reset"]) + run_cmd(["netsh", "int", "ip", "reset"])
    elif fix_id == "use_public_dns":
        if not interface:
            raise RuntimeError("No active adapter found")
        out = run_cmd(["netsh", "interface", "ip", "set", "dns", f"name={interface}", "static", "1.1.1.1"])
        out += run_cmd(["netsh", "interface", "ip", "add", "dns", f"name={interface}", "1.0.0.1", "index=2"])
    return (out or "Done").strip()[-600:]


def _tcp_time(host, port=443, timeout=4, family=socket.AF_UNSPEC):
    start = time.perf_counter()
    try:
        infos = socket.getaddrinfo(host, port, family, socket.SOCK_STREAM)
        fam, _, _, _, addr = infos[0]
        s = socket.socket(fam, socket.SOCK_STREAM)
        s.settimeout(timeout)
        t = time.perf_counter()
        s.connect(addr)
        s.close()
        return (time.perf_counter() - t) * 1000, addr[0], (t - start) * 1000
    except Exception:
        return None, None, None


def troubleshoot(engine):
    """Runs a chain of checks from the adapter outwards. Returns a list of step dicts."""
    steps = []
    net = netops.get_network_info()

    def step(sid, title, status, detail, fixes=()):
        steps.append({"id": sid, "title": title, "status": status, "detail": detail, "fixes": list(fixes)})
        return status

    # 1 adapter
    ip = net.get("local_ip")
    if not ip:
        step("adapter", "Network adapter", "fail", "This PC has no network connection. Check the cable or Wi-Fi.",
             ["reset_adapter"])
        return steps
    if ip.startswith("169.254."):
        step("adapter", "Network adapter", "fail", f"Got a self-assigned address ({ip}) - the router didn't hand "
             f"out an IP. Restarting the router or renewing the IP usually fixes this.", ["renew_ip", "reset_adapter"])
        return steps
    step("adapter", "Network adapter", "ok", f"{net.get('interface') or 'Adapter'} is up with address {ip}" +
         (f" at {net['link_speed']} Mbps" if net.get("link_speed") else ""))

    # 2 Wi-Fi
    w = netops.wifi_status()
    if w and not w.get("error") and w.get("connected"):
        sig = w.get("signal") or 0
        step("wifi", "Wi-Fi signal", "ok" if sig >= 50 else "warn" if sig >= 30 else "fail",
             f"{w.get('ssid')} at {sig:.0f}% on {w.get('band', '')} channel {w.get('channel')}" +
             ("" if sig >= 50 else " - weak signal causes drop-outs and slow speeds. Move closer to the router."))

    # 3 router
    gw = net.get("gateway")
    if gw:
        rtts = [winapi.ping(gw, 800) for _ in range(5)]
        ok = [r for r in rtts if r is not None]
        if not ok:
            step("router", "Router", "fail", f"Your router ({gw}) isn't responding. Check it's powered on, then try "
                 f"restarting it.", ["reset_adapter"])
            return steps
        avg = sum(ok) / len(ok)
        step("router", "Router", "ok" if avg < 20 and len(ok) == 5 else "warn",
             f"Router {gw} answers in {avg:.0f} ms ({len(ok)}/5 replies)" +
             ("" if avg < 20 else " - slow for a local hop, which points at Wi-Fi interference or a busy router."))
    else:
        step("router", "Router", "warn", "No default gateway - this PC doesn't know how to reach the internet.",
             ["renew_ip"])

    # 4 internet by IP
    ext = [winapi.ping(h, 1000) for h in ("1.1.1.1", "8.8.8.8", "1.1.1.1")]
    eok = [r for r in ext if r is not None]
    if not eok:
        tcp, _, _ = _tcp_time("1.1.1.1", 443)
        if tcp is None:
            step("internet", "Internet connection", "fail", "Your router is fine but nothing beyond it answers. "
                 "This is almost certainly an ISP fault - check their status page or restart the router.")
            return steps
        step("internet", "Internet connection", "warn", "Ping is blocked but web traffic gets through.")
    else:
        step("internet", "Internet connection", "ok", f"Internet servers reachable in {min(eok):.0f} ms")

    # 5 DNS
    try:
        t = time.perf_counter()
        socket.getaddrinfo("www.microsoft.com", 443)
        ms = (time.perf_counter() - t) * 1000
        step("dns", "DNS (name lookups)", "ok" if ms < 150 else "warn",
             f"Website names resolve in {ms:.0f} ms" + ("" if ms < 150 else " - slower than ideal."),
             [] if ms < 150 else ["flush_dns", "use_public_dns"])
    except OSError:
        sysd = winapi.system_dns_servers()
        pub, ok_pub, _ = netops.dns_query("1.1.1.1", "www.microsoft.com")
        step("dns", "DNS (name lookups)", "fail",
             "Name lookups are failing" + (", but Cloudflare's DNS works - your DNS server "
                                           f"({', '.join(sysd) or 'router'}) is the problem." if ok_pub else "."),
             ["flush_dns", "use_public_dns"])

    # 6 web / captive portal
    from .security import captive_portal_check
    cp = captive_portal_check()
    if cp.get("portal"):
        step("web", "Web access", "fail", "A login page is intercepting your traffic (hotel / café / guest Wi-Fi). "
             "Open a browser to sign in.")
    elif cp.get("portal") is False:
        tls, _, _ = _tcp_time("www.bbc.co.uk", 443)
        step("web", "Web access", "ok", "Websites load normally" + (f" (connect {tls:.0f} ms)" if tls else ""))
    else:
        step("web", "Web access", "warn", f"Couldn't fetch a test page: {cp.get('error', '')}")

    # 7 quality
    snap = engine.snapshot() if engine else {}
    q = quality(snap.get("latency"), snap.get("jitter"), snap.get("loss"))
    if q:
        bad = q["calls"] in ("Poor", "Bad") or (snap.get("loss") or 0) > 2
        step("quality", "Connection quality", "warn" if bad else "ok",
             f"Video calls: {q['calls']} · Gaming: {q['gaming']} · latency {snap.get('latency') or 0:.0f} ms, "
             f"jitter {snap.get('jitter') or 0:.1f} ms, loss {snap.get('loss') or 0:.1f}%")

    # 8 IPv6
    v6 = ipv6_health()
    if v6["status"] == "broken":
        step("ipv6", "IPv6", "warn", v6["detail"])
    elif v6["status"] in ("ok", "none"):
        step("ipv6", "IPv6", "ok", v6["detail"])
    return steps


# --------------------------------------------------------------------------- #
# Microsoft 365 & cloud latency
# --------------------------------------------------------------------------- #

M365_ENDPOINTS = [
    ("Exchange Online / Outlook", "outlook.office365.com"),
    ("Microsoft Teams", "teams.microsoft.com"),
    ("SharePoint / OneDrive", "microsoft.sharepoint.com"),
    ("Sign-in (Entra ID)", "login.microsoftonline.com"),
    ("Office web apps", "www.office.com"),
]


def _proxy_info():
    if not IS_WINDOWS:
        return {"winhttp": "n/a", "user": False}
    out = run_cmd(["netsh", "winhttp", "show", "proxy"])
    direct = "direct access" in out.lower()
    m = re.search(r"Proxy Server\(s\)\s*:\s*(\S+)", out)
    user = False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                            r"Software\Microsoft\Windows\CurrentVersion\Internet Settings") as k:
            user = bool(winreg.QueryValueEx(k, "ProxyEnable")[0])
    except Exception:
        pass
    return {"winhttp": "Direct" if direct else (m.group(1) if m else "Configured"), "user": user}


def resolver_egress():
    """The public IP your DNS resolver uses (Akamai 'whoami' trick)."""
    try:
        return socket.gethostbyname("whoami.akamai.net")
    except OSError:
        return None


def m365_test():
    results = []

    def one(item):
        name, host = item
        t = time.perf_counter()
        try:
            canon = socket.gethostbyname_ex(host)
            dns_ms = (time.perf_counter() - t) * 1000
        except OSError:
            return {"name": name, "host": host, "error": "DNS lookup failed"}
        conn = [x for x in (_tcp_time(host, 443)[0] for _ in range(3)) if x is not None]
        tls = None
        try:
            ctx = ssl.create_default_context()
            with socket.create_connection((host, 443), timeout=5) as s:
                t2 = time.perf_counter()
                with ctx.wrap_socket(s, server_hostname=host):
                    tls = (time.perf_counter() - t2) * 1000
        except Exception:
            pass
        cname = canon[0] if canon and canon[0] != host else ""
        tcp = min(conn) if conn else None
        grade = None if tcp is None else "Excellent" if tcp < 25 else "Good" if tcp < 50 else \
            "Fair" if tcp < 100 else "Poor"
        return {"name": name, "host": host, "ip": canon[2][0] if canon[2] else "", "cname": cname,
                "dns_ms": round(dns_ms, 1), "tcp_ms": None if tcp is None else round(tcp, 1),
                "tls_ms": None if tls is None else round(tls, 1), "grade": grade}

    with ThreadPoolExecutor(max_workers=5) as pool:
        results = list(pool.map(one, M365_ENDPOINTS))
    proxy = _proxy_info()
    egress = resolver_egress()
    notes = []
    if proxy["winhttp"] not in ("Direct", "n/a") or proxy["user"]:
        notes.append("A proxy is configured. Microsoft recommends sending Microsoft 365 traffic directly, "
                     "bypassing proxies, for the best Teams and Outlook performance.")
    slow = [r for r in results if r.get("grade") in ("Fair", "Poor")]
    if slow:
        notes.append("Some Microsoft 365 services are slow to connect, which suggests your traffic isn't reaching "
                     "Microsoft's nearest entry point - often caused by VPNs, proxies or a distant DNS resolver.")
    return {"endpoints": results, "proxy": proxy, "resolver_egress": egress, "notes": notes}


CLOUD_REGIONS = [
    ("AWS London", "dynamodb.eu-west-2.amazonaws.com"),
    ("AWS Ireland", "dynamodb.eu-west-1.amazonaws.com"),
    ("AWS Frankfurt", "dynamodb.eu-central-1.amazonaws.com"),
    ("AWS Stockholm", "dynamodb.eu-north-1.amazonaws.com"),
    ("AWS N. Virginia", "dynamodb.us-east-1.amazonaws.com"),
    ("AWS Oregon", "dynamodb.us-west-2.amazonaws.com"),
    ("AWS São Paulo", "dynamodb.sa-east-1.amazonaws.com"),
    ("AWS Mumbai", "dynamodb.ap-south-1.amazonaws.com"),
    ("AWS Singapore", "dynamodb.ap-southeast-1.amazonaws.com"),
    ("AWS Tokyo", "dynamodb.ap-northeast-1.amazonaws.com"),
    ("AWS Sydney", "dynamodb.ap-southeast-2.amazonaws.com"),
]


def cloud_latency(custom=()):
    targets = list(CLOUD_REGIONS)
    for c in custom or []:
        c = c.strip()
        if c:
            targets.append((c, c))

    def one(t):
        name, target = t
        host, _, port = target.rpartition(":") if target.count(":") == 1 else (target, "", "443")
        vals = [x for x in (_tcp_time(host or target, int(port or 443), timeout=3)[0] for _ in range(3)) if x]
        return {"name": name, "host": target, "ms": round(min(vals), 1) if vals else None,
                "custom": t not in CLOUD_REGIONS}
    with ThreadPoolExecutor(max_workers=8) as pool:
        out = list(pool.map(one, targets))
    return sorted(out, key=lambda x: (x["ms"] is None, x["ms"] or 0))


# --------------------------------------------------------------------------- #
# "Is it just me?"
# --------------------------------------------------------------------------- #

MAJOR_SITES = [("Google", "www.google.com"), ("Cloudflare", "www.cloudflare.com"), ("Microsoft", "www.microsoft.com"),
               ("Amazon", "www.amazon.co.uk"), ("BBC", "www.bbc.co.uk"), ("Netflix", "www.netflix.com"),
               ("YouTube", "www.youtube.com"), ("Apple", "www.apple.com"), ("Facebook", "www.facebook.com"),
               ("WhatsApp", "web.whatsapp.com"), ("GitHub", "github.com"), ("Wikipedia", "www.wikipedia.org")]


def is_it_just_me(extra=None):
    sites = list(MAJOR_SITES)
    if extra:
        h = re.sub(r"^https?://", "", extra.strip()).split("/")[0]
        if h:
            sites.insert(0, (h, h))

    def one(s):
        name, host = s
        ok, ms, detail = netops.check_http("https://" + host, timeout=8)
        return {"name": name, "host": host, "ok": ok or (detail.startswith("HTTP") and not detail.startswith("HTTP 5")),
                "ms": None if ms is None else round(ms), "detail": detail}
    with ThreadPoolExecutor(max_workers=12) as pool:
        res = list(pool.map(one, sites))
    up = [r for r in res if r["ok"]]
    if not up:
        verdict = "It's you: nothing is reachable, so the problem is your connection (or your ISP), not the websites."
    elif len(up) == len(res):
        verdict = "It's not you: every site we tried is reachable from your connection."
    else:
        down = [r["name"] for r in res if not r["ok"]]
        verdict = f"Your connection works. {', '.join(down)} {'is' if len(down) == 1 else 'are'} having problems " \
                  f"or blocking access."
    return {"sites": res, "verdict": verdict}


# --------------------------------------------------------------------------- #
# IPv6
# --------------------------------------------------------------------------- #

def ipv6_health():
    addrs = []
    if psutil:
        for name, lst in psutil.net_if_addrs().items():
            for a in lst:
                if a.family == socket.AF_INET6:
                    try:
                        ip = ipaddress.IPv6Address(a.address.split("%")[0])
                    except ValueError:
                        continue
                    if ip.is_global:
                        addrs.append({"interface": name, "address": str(ip)})
    v4, _, _ = _tcp_time("1.1.1.1", 443, family=socket.AF_INET)
    if not addrs:
        return {"status": "none", "addresses": [], "v4_ms": v4, "v6_ms": None,
                "detail": "No IPv6 on this network. That's fine - everything works over IPv4."}
    v6, _, _ = _tcp_time("2606:4700:4700::1111", 443, family=socket.AF_INET6)
    dns6 = True
    try:
        socket.getaddrinfo("www.google.com", 443, socket.AF_INET6)
    except OSError:
        dns6 = False
    if v6 is None:
        return {"status": "broken", "addresses": addrs, "v4_ms": v4, "v6_ms": None, "dns": dns6,
                "detail": "You have an IPv6 address but IPv6 traffic isn't getting through. Apps try IPv6 first and "
                          "wait for it to fail, which causes slow page loads. Restart the router or disable IPv6."}
    cmp = "" if v4 is None else (" - faster than IPv4" if v6 < v4 * 0.9 else
                                 " - slower than IPv4" if v6 > v4 * 1.3 else " - about the same as IPv4")
    return {"status": "ok", "addresses": addrs, "v4_ms": v4, "v6_ms": v6, "dns": dns6,
            "detail": f"IPv6 works ({v6:.0f} ms{cmp})."}


# --------------------------------------------------------------------------- #
# VPN
# --------------------------------------------------------------------------- #

VPN_HINTS = ("vpn", "wireguard", "wg", "openvpn", "tap-windows", "tap", "tun", "nordlynx", "anyconnect", "cisco",
             "fortinet", "forticlient", "globalprotect", "pangp", "zscaler", "tailscale", "zerotier", "proton",
             "mullvad", "expressvpn", "surfshark", "juniper", "pulse", "ppp", "f5 ", "checkpoint", "sonicwall")


def vpn_adapters():
    out = []
    if not psutil:
        return out
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    for name, st in stats.items():
        n = name.lower()
        if not any(re.search(rf"(^|[^a-z]){re.escape(h.strip())}([^a-z]|$)", n) for h in VPN_HINTS):
            continue
        has_ip = any(a.family == socket.AF_INET for a in addrs.get(name, []))
        out.append({"name": name, "up": bool(st.isup and has_ip)})
    return out


def leak_test(geo_lookup=None):
    pub = netops.fetch_public_ip() or {}
    egress = resolver_egress()
    result = {"public_ip": pub.get("ip"), "public_isp": pub.get("isp"), "public_city": pub.get("city"),
              "resolver_ip": egress, "resolver_isp": None, "vpn": [a for a in vpn_adapters() if a["up"]]}
    if geo_lookup and egress:
        g = geo_lookup([egress]).get(egress) or {}
        result["resolver_isp"] = g.get("isp")
        result["resolver_country"] = g.get("country")
    return result


# --------------------------------------------------------------------------- #
# DNS cache -> which domains apps talk to
# --------------------------------------------------------------------------- #

if IS_WINDOWS:
    from ctypes import wintypes

    class DNS_CACHE_ENTRY(ctypes.Structure):
        pass
    DNS_CACHE_ENTRY._fields_ = [("pNext", ctypes.POINTER(DNS_CACHE_ENTRY)), ("pszName", ctypes.c_wchar_p),
                                ("wType", ctypes.c_ushort), ("wDataLength", ctypes.c_ushort),
                                ("dwFlags", ctypes.c_ulong)]

    class DNS_RECORDW(ctypes.Structure):
        pass
    DNS_RECORDW._fields_ = [("pNext", ctypes.POINTER(DNS_RECORDW)), ("pName", ctypes.c_wchar_p),
                            ("wType", ctypes.c_ushort), ("wDataLength", ctypes.c_ushort),
                            ("Flags", ctypes.c_ulong), ("dwTtl", ctypes.c_ulong), ("dwReserved", ctypes.c_ulong),
                            ("Data", ctypes.c_ubyte * 16)]
    try:
        _dnsapi = ctypes.WinDLL("dnsapi.dll")
    except OSError:
        _dnsapi = None


def dns_cache_map(max_names=600):
    """{ip: domain} built from the Windows DNS client cache (no network queries)."""
    if not IS_WINDOWS or _dnsapi is None:
        return {}
    head = ctypes.POINTER(DNS_CACHE_ENTRY)()
    try:
        if not _dnsapi.DnsGetCacheDataTable(ctypes.byref(head)):
            return {}
    except Exception:
        return {}
    names = []
    node = head
    while node and len(names) < max_names:
        e = node.contents
        if e.pszName and e.wType in (1, 28):
            names.append((e.pszName, e.wType))
        node = e.pNext
    out = {}
    for name, rtype in names:
        rec = ctypes.POINTER(DNS_RECORDW)()
        try:
            status = _dnsapi.DnsQuery_W(name, rtype, 0x10, None, ctypes.byref(rec), None)  # NO_WIRE_QUERY
        except Exception:
            continue
        if status != 0 or not rec:
            continue
        r = rec
        while r:
            d = r.contents
            try:
                if d.wType == 1:
                    out[socket.inet_ntoa(bytes(d.Data[:4]))] = name.lower()
                elif d.wType == 28:
                    out[socket.inet_ntop(socket.AF_INET6, bytes(d.Data[:16]))] = name.lower()
            except (OSError, ValueError):
                pass
            r = d.pNext
        try:
            _dnsapi.DnsRecordListFree(rec, 1)
        except Exception:
            pass
    return out


TRACKERS = (
    "doubleclick.net", "google-analytics.com", "googletagmanager.com", "googlesyndication.com", "googleadservices.com",
    "adservice.google.com", "app-measurement.com", "facebook.net", "connect.facebook.net", "graph.facebook.com",
    "scorecardresearch.com", "quantserve.com", "criteo.com", "criteo.net", "taboola.com", "outbrain.com",
    "adnxs.com", "rubiconproject.com", "pubmatic.com", "openx.net", "casalemedia.com", "moatads.com",
    "amazon-adsystem.com", "adsrvr.org", "bing.com/action", "bat.bing.com", "clarity.ms", "hotjar.com", "hotjar.io",
    "mixpanel.com", "segment.io", "segment.com", "amplitude.com", "branch.io", "appsflyer.com", "adjust.com",
    "newrelic.com", "nr-data.net", "sentry.io", "bugsnag.com", "crashlytics.com", "demdex.net", "omtrdc.net",
    "everesttech.net", "chartbeat.com", "chartbeat.net", "optimizely.com", "doubleverify.com", "teads.tv",
    "smartadserver.com", "yieldmo.com", "media.net", "zemanta.com", "tiktokv.com", "ads.tiktok.com",
    "analytics.tiktok.com", "ads.linkedin.com", "px.ads.linkedin.com", "snap.licdn.com", "ads-twitter.com",
    "analytics.twitter.com", "static.ads-twitter.com", "pinterest.com/ct", "ct.pinterest.com", "vortex.data.microsoft.com",
    "telemetry.microsoft.com", "settings-win.data.microsoft.com", "watson.telemetry.microsoft.com",
    "browser.events.data.msn.com", "mobile.events.data.microsoft.com", "self.events.data.microsoft.com",
    "metrics.icloud.com", "iadsdk.apple.com", "samsungads.com", "samsungacr.com", "ads.yahoo.com", "adtech.yahooinc.com",
)


def is_tracker(domain):
    d = (domain or "").lower()
    return any(d == t or d.endswith("." + t) for t in TRACKERS)


def base_domain(domain):
    parts = (domain or "").lower().strip(".").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net", "gov", "ac") and len(parts[-1]) == 2:
        return ".".join(parts[-3:])
    return ".".join(parts[-2:])


# --------------------------------------------------------------------------- #
# GeoIP (ip-api.com batch, opt-in)
# --------------------------------------------------------------------------- #

def geo_batch(ips):
    ips = [ip for ip in ips if _is_public(ip)][:100]
    if not ips:
        return {}
    body = json.dumps([{"query": ip, "fields": "status,country,countryCode,city,lat,lon,isp,org,as,query"}
                       for ip in ips]).encode()
    req = urllib.request.Request("http://ip-api.com/batch", data=body,
                                 headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=10) as r:
        data = json.loads(r.read().decode())
    return {d["query"]: {"country": d.get("country"), "cc": d.get("countryCode"), "city": d.get("city"),
                         "lat": d.get("lat"), "lon": d.get("lon"), "isp": d.get("isp"), "org": d.get("org"),
                         "as": d.get("as")}
            for d in data if d.get("status") == "success"}


def _is_public(ip):
    try:
        return ipaddress.ip_address(ip).is_global
    except ValueError:
        return False


# --------------------------------------------------------------------------- #
# TLS certificate expiry
# --------------------------------------------------------------------------- #

def cert_expiry(host, port=443, timeout=6):
    host = re.sub(r"^https?://", "", host).split("/")[0]
    if ":" in host:
        host, port = host.split(":", 1)
    ctx = ssl.create_default_context()
    with socket.create_connection((host, int(port)), timeout=timeout) as s:
        with ctx.wrap_socket(s, server_hostname=host) as t:
            cert = t.getpeercert()
    exp = datetime.strptime(cert["notAfter"], "%b %d %H:%M:%S %Y %Z").replace(tzinfo=timezone.utc)
    issuer = dict(x[0] for x in cert.get("issuer", ())).get("organizationName", "")
    return {"expires": exp.timestamp(), "days": (exp - datetime.now(timezone.utc)).days, "issuer": issuer}
