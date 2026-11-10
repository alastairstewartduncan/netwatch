"""Network operations: discovery, vendors, port scans, Wake-on-LAN, traceroute, DNS, Wi-Fi, checks."""

import csv
import gzip
import io
import ipaddress
import json
import random
import re
import socket
import ssl
import struct
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor

from . import winapi
from .winapi import IS_WINDOWS, run_cmd

try:
    import psutil
except ImportError:
    psutil = None

USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetWatch/2.0"


def is_ipv4(text):
    try:
        ipaddress.IPv4Address(text)
        return True
    except (ValueError, TypeError):
        return False


def norm_mac(mac):
    return mac.replace("-", ":").upper() if mac else ""


def is_random_mac(mac):
    """Locally administered bit set -> privacy / randomised MAC (typical of phones)."""
    try:
        return bool(int(mac.split(":")[0], 16) & 0x02)
    except (ValueError, IndexError, AttributeError):
        return False


# --------------------------------------------------------------------------- #
# Local network info
# --------------------------------------------------------------------------- #

def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def get_default_gateway():
    if IS_WINDOWS:
        best = None
        for line in run_cmd(["route", "print", "-4", "0.0.0.0"]).splitlines():
            p = line.split()
            if len(p) >= 5 and p[0] == "0.0.0.0" and p[1] == "0.0.0.0" and is_ipv4(p[2]):
                metric = int(p[4]) if p[4].isdigit() else 9999
                if best is None or metric < best[1]:
                    best = (p[2], metric)
        return best[0] if best else None
    m = re.search(r"default via (\S+)", run_cmd(["ip", "route", "show", "default"]))
    return m.group(1) if m else None


def get_network_info():
    info = {"local_ip": get_local_ip(), "gateway": get_default_gateway(),
            "network": None, "mac": "", "interface": "", "link_speed": None}
    ip = info["local_ip"]
    if not ip:
        return info
    netmask = "255.255.255.0"
    if psutil:
        for name, addrs in psutil.net_if_addrs().items():
            if any(a.family == socket.AF_INET and a.address == ip for a in addrs):
                info["interface"] = name
                for a in addrs:
                    if a.family == socket.AF_INET and a.address == ip and a.netmask:
                        netmask = a.netmask
                    if a.family == psutil.AF_LINK:
                        info["mac"] = norm_mac(a.address)
                st = psutil.net_if_stats().get(name)
                if st and st.speed:
                    info["link_speed"] = st.speed
                break
    net = ipaddress.IPv4Network(f"{ip}/{netmask}", strict=False)
    if net.prefixlen < 24:
        net = ipaddress.IPv4Network(f"{ip}/24", strict=False)
    info["network"] = str(net)
    return info


MAC_RE = re.compile(r"([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})")
IP_RE = re.compile(r"(\d{1,3}(?:\.\d{1,3}){3})")


def read_arp_table():
    table = {}
    for line in run_cmd(["arp", "-a"]).splitlines():
        ipm, macm = IP_RE.search(line), MAC_RE.search(line)
        if ipm and macm:
            mac = norm_mac(macm.group(1))
            if mac == "FF:FF:FF:FF:FF:FF" or mac.startswith("01:00:5E") or mac.startswith("33:33"):
                continue
            table[ipm.group(1)] = mac
    return table


def reverse_dns(ip):
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return ""


def scan_network(net_info, progress_cb=None):
    network = ipaddress.IPv4Network(net_info["network"])
    hosts = [str(h) for h in network.hosts()]
    results = {}
    done = 0
    with ThreadPoolExecutor(max_workers=64) as pool:
        for ip, rtt in pool.map(lambda h: (h, winapi.ping(h, 700)), hosts):
            done += 1
            if rtt is not None:
                results[ip] = {"ip": ip, "rtt": rtt}
            if progress_cb and (done % 8 == 0 or done == len(hosts)):
                progress_cb(done, len(hosts))
    for ip, mac in read_arp_table().items():
        try:
            if ipaddress.ip_address(ip) in network and ip != str(network.broadcast_address):
                results.setdefault(ip, {"ip": ip, "rtt": None})["mac"] = mac
        except ValueError:
            pass
    own = net_info.get("local_ip")
    if own:
        e = results.setdefault(own, {"ip": own, "rtt": 0.0})
        e["mac"] = net_info.get("mac", "")
        e["self"] = True
    gw = net_info.get("gateway")
    if gw in results:
        results[gw]["gateway"] = True
    with ThreadPoolExecutor(max_workers=32) as pool:
        for ip, name in zip(list(results), pool.map(reverse_dns, list(results))):
            results[ip]["hostname"] = name
    return list(results.values())


# --------------------------------------------------------------------------- #
# MAC vendor lookup (IEEE OUI registry, downloaded once and cached)
# --------------------------------------------------------------------------- #

class VendorDB:
    SOURCES = ["https://standards-oui.ieee.org/oui/oui.csv",
               "https://www.wireshark.org/download/automated/data/manuf"]

    def __init__(self, cache_path):
        self.path = cache_path
        self.db = {}
        self.loaded = False
        try:
            with gzip.open(self.path, "rt", encoding="utf-8") as fh:
                self.db = json.load(fh)
                self.loaded = bool(self.db)
        except (OSError, ValueError):
            pass

    def age_days(self):
        try:
            return (time.time() - self.path.stat().st_mtime) / 86400
        except OSError:
            return 9999

    def update(self):
        for url in self.SOURCES:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
                with urllib.request.urlopen(req, timeout=60) as r:
                    text = r.read().decode("utf-8", errors="replace")
                db = self._parse_csv(text) if url.endswith(".csv") else self._parse_manuf(text)
                if len(db) > 1000:
                    self.db = db
                    self.loaded = True
                    self.path.parent.mkdir(parents=True, exist_ok=True)
                    with gzip.open(self.path, "wt", encoding="utf-8") as fh:
                        json.dump(db, fh)
                    return True
            except Exception:
                continue
        return False

    @staticmethod
    def _parse_csv(text):
        db = {}
        for row in csv.reader(io.StringIO(text)):
            if len(row) >= 3 and len(row[1]) == 6:
                db[row[1].upper()] = row[2].strip()
        return db

    @staticmethod
    def _parse_manuf(text):
        db = {}
        for line in text.splitlines():
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2 and len(parts[0]) == 8:
                db[parts[0].replace(":", "").upper()] = (parts[2] if len(parts) > 2 else parts[1]).strip()
        return db

    def lookup(self, mac):
        if not mac:
            return ""
        if is_random_mac(mac):
            return "Private (randomised) MAC"
        return self.db.get(mac.replace(":", "")[:6].upper(), "")


def short_vendor(vendor):
    v = re.sub(r"[,.]?\s*(inc|ltd|llc|co|corp|corporation|limited|gmbh|technologies|technology|"
               r"electronics|international|communications|company)\b\.?", "", vendor or "", flags=re.I)
    return re.sub(r"\s+", " ", v).strip(" ,.") or (vendor or "")


TYPE_RULES = [
    ("printer", r"printer|brother|epson|canon|lexmark|kyocera|hewlett|\bhp\b|xerox"),
    ("tv", r"tv|roku|chromecast|bravia|vizio|hisense|tcl|firetv|fire-tv|lg electronics|samsung.*tv|webos|appletv"),
    ("speaker", r"sonos|echo|alexa|homepod|google-home|nest-audio|bose|amazon"),
    ("console", r"xbox|playstation|nintendo|sony interactive|ps[345]"),
    ("camera", r"camera|\bring\b|hikvision|dahua|reolink|arlo|wyze|axis comm|eufy|blink"),
    ("nas", r"synology|qnap|nas|diskstation|western digital|truenas"),
    ("network", r"tp-?link|netgear|ubiquiti|unifi|cisco|linksys|asus.*router|eero|deco|mesh|"
                r"aruba|mikrotik|draytek|zyxel|plume|orbi|bt-|sky-|virgin|switch|access point"),
    ("iot", r"espressif|tuya|shelly|raspberry|sonoff|hue|philips light|signify|nest|ecobee|tado|"
            r"hive|meross|smart|wiz|lifx|esp_|esp-|arduino|particle|myenergi|octopus"),
    ("phone", r"iphone|android|galaxy|pixel|oneplus|xiaomi|huawei|oppo|vivo|motorola|nokia|phone|"
              r"randomised"),
    ("tablet", r"ipad|tablet|kindle|fire-hd"),
    ("pc", r"desktop|laptop|pc|macbook|imac|mac-mini|thinkpad|surface|dell|lenovo|intel corporate|"
           r"micro-star|msi|gigabyte|asustek|workstation|-win|win-"),
]

PORT_TYPES = {9100: "printer", 631: "printer", 515: "printer", 8009: "tv", 554: "camera",
              5000: "nas", 5001: "nas", 1883: "iot", 8123: "iot", 3389: "pc", 445: "pc", 62078: "phone"}


def guess_type(dev):
    if dev.get("self"):
        return "pc"
    if dev.get("gateway"):
        return "router"
    text = " ".join([dev.get("hostname", ""), dev.get("vendor", ""), dev.get("name", "")]).lower()
    for t, pattern in TYPE_RULES:
        if re.search(pattern, text):
            return t
    for p in dev.get("ports") or []:
        port = p.get("port") if isinstance(p, dict) else p
        if port in PORT_TYPES:
            return PORT_TYPES[port]
    return "device"


# --------------------------------------------------------------------------- #
# Port scan & Wake-on-LAN
# --------------------------------------------------------------------------- #

COMMON_PORTS = {
    21: "FTP", 22: "SSH", 23: "Telnet", 25: "SMTP", 53: "DNS", 80: "HTTP", 110: "POP3",
    135: "MS RPC", 139: "NetBIOS", 143: "IMAP", 443: "HTTPS", 445: "SMB file sharing",
    515: "LPD printing", 548: "AFP", 554: "RTSP camera", 631: "IPP printing", 1883: "MQTT",
    1900: "UPnP", 3000: "Web app", 3306: "MySQL", 3389: "Remote Desktop", 5000: "Synology / web",
    5001: "Synology HTTPS", 5353: "mDNS", 5900: "VNC", 7000: "AirPlay", 8000: "Web alt",
    8008: "Chromecast", 8009: "Chromecast", 8080: "HTTP alt", 8123: "Home Assistant",
    8443: "HTTPS alt", 8888: "Web alt", 9000: "Web admin", 9100: "Printer (RAW)",
    32400: "Plex", 49152: "UPnP", 62078: "Apple iDevice sync",
}
RISKY_PORTS = {21, 23, 135, 139, 445, 3389, 5900}


def port_scan(ip, ports=None, timeout=0.5):
    ports = ports or sorted(COMMON_PORTS)

    def probe(p):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(timeout)
        try:
            return p if s.connect_ex((ip, p)) == 0 else None
        except OSError:
            return None
        finally:
            s.close()

    with ThreadPoolExecutor(max_workers=48) as pool:
        open_ports = [p for p in pool.map(probe, ports) if p]
    return [{"port": p, "service": COMMON_PORTS.get(p, ""), "risky": p in RISKY_PORTS} for p in open_ports]


def wake_on_lan(mac, broadcast_addrs=("255.255.255.255",)):
    clean = re.sub(r"[^0-9A-Fa-f]", "", mac or "")
    if len(clean) != 12:
        raise ValueError("Invalid MAC address")
    packet = b"\xff" * 6 + bytes.fromhex(clean) * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        for addr in broadcast_addrs:
            for port in (9, 7):
                try:
                    s.sendto(packet, (addr, port))
                except OSError:
                    pass
    return True


# --------------------------------------------------------------------------- #
# Traceroute (ICMP with increasing TTL)
# --------------------------------------------------------------------------- #

def traceroute(host, max_hops=30, probes=3, timeout_ms=900, on_hop=None, should_stop=lambda: False):
    try:
        dest = socket.gethostbyname(host)
    except OSError as exc:
        raise ValueError(f"Could not resolve {host}") from exc
    hops = []
    for ttl in range(1, max_hops + 1):
        if should_stop():
            break
        rtts, addr, reached = [], None, False
        for _ in range(probes):
            r = winapi.icmp_echo(dest, timeout_ms, ttl)
            if r and r[0] in (winapi.IP_SUCCESS, winapi.IP_TTL_EXPIRED_TRANSIT):
                rtts.append(r[1])
                addr = r[2]
                reached = reached or r[0] == winapi.IP_SUCCESS or r[2] == dest
            else:
                rtts.append(None)
        ok = [x for x in rtts if x is not None]
        hop = {"hop": ttl, "ip": addr or "", "host": "", "rtts": rtts,
               "avg": round(sum(ok) / len(ok), 1) if ok else None,
               "loss": round(100 * (len(rtts) - len(ok)) / len(rtts)),
               "private": bool(addr) and ipaddress.ip_address(addr).is_private}
        hops.append(hop)
        if on_hop:
            on_hop(hop)
        if addr:
            hop["host"] = reverse_dns(addr)
            if on_hop:
                on_hop(hop)
        if reached:
            break
    return dest, hops


# --------------------------------------------------------------------------- #
# DNS (raw UDP query so we can time each resolver independently)
# --------------------------------------------------------------------------- #

def dns_query(server, name, timeout=2.0):
    """Returns (ms, ok, answer_count). ok is False on timeout or SERVFAIL/REFUSED."""
    tid = random.randint(0, 0xFFFF)
    packet = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    packet += b"".join(bytes([len(p)]) + p.encode("ascii") for p in name.strip(".").split(".")) + b"\x00"
    packet += struct.pack(">HH", 1, 1)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        start = time.perf_counter()
        s.sendto(packet, (server, 53))
        while True:
            data, _ = s.recvfrom(1500)
            if len(data) >= 12 and struct.unpack(">H", data[:2])[0] == tid:
                ms = (time.perf_counter() - start) * 1000
                rcode = data[3] & 0x0F
                answers = struct.unpack(">H", data[6:8])[0]
                return ms, rcode in (0, 3), answers
    except OSError:
        return None, False, 0
    finally:
        s.close()


# --------------------------------------------------------------------------- #
# Service checks
# --------------------------------------------------------------------------- #

def check_http(url, timeout=10):
    if not re.match(r"https?://", url, re.I):
        url = "https://" + url
    start = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        ctx = ssl.create_default_context()
        with urllib.request.urlopen(req, timeout=timeout, context=ctx) as r:
            r.read(2048)
            code = r.status
        ms = (time.perf_counter() - start) * 1000
        return code < 400, ms, f"HTTP {code}"
    except urllib.error.HTTPError as e:
        return False, (time.perf_counter() - start) * 1000, f"HTTP {e.code}"
    except Exception as e:
        reason = getattr(e, "reason", e)
        return False, None, str(reason)[:80]


def check_tcp(host, port, timeout=5):
    start = time.perf_counter()
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True, (time.perf_counter() - start) * 1000, f"Port {port} open"
    except Exception as e:
        return False, None, str(e)[:80]


def check_ping(host, timeout_ms=1500):
    try:
        ip = host if is_ipv4(host) else socket.gethostbyname(host)
    except OSError:
        return False, None, "DNS lookup failed"
    rtt = winapi.ping(ip, timeout_ms)
    return (rtt is not None), rtt, "Reply" if rtt is not None else "No reply"


def run_check(check):
    t = check.get("type", "http")
    target = check.get("target", "")
    if t == "tcp":
        host, _, port = target.rpartition(":")
        return check_tcp(host or target, port or 80)
    if t == "ping":
        return check_ping(target)
    return check_http(target)


# --------------------------------------------------------------------------- #
# Public IP / ISP
# --------------------------------------------------------------------------- #

def fetch_public_ip():
    for url in ("https://speed.cloudflare.com/meta", "https://ipinfo.io/json"):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=8) as r:
                d = json.loads(r.read().decode())
            return {"ip": d.get("clientIp") or d.get("ip", ""),
                    "isp": d.get("asOrganization") or d.get("org", ""),
                    "city": d.get("city", ""), "country": d.get("country", "")}
        except Exception:
            continue
    return None


# --------------------------------------------------------------------------- #
# Wi-Fi (netsh)
# --------------------------------------------------------------------------- #

def _kv_lines(text):
    for line in text.splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            yield k.strip().lower(), v.strip()


def wifi_status():
    """Current Wi-Fi connection. None if no Wi-Fi adapter / not Windows."""
    if not IS_WINDOWS:
        return None
    out = run_cmd(["netsh", "wlan", "show", "interfaces"], timeout=10)
    if not out.strip():
        return None
    if "location" in out.lower() and "permission" in out.lower():
        return {"error": "location"}
    info = {}
    for k, v in _kv_lines(out):
        if k == "name" and "name" in info:
            break  # only first adapter
        if k == "ssid":
            info["ssid"] = v
        elif k in ("ap bssid", "bssid"):
            info["bssid"] = v.upper()
        elif k == "name":
            info["name"] = v
        elif k == "state":
            info["state"] = v
        elif k == "radio type":
            info["radio"] = v
        elif k == "band":
            info["band"] = v
        elif k == "channel":
            info["channel"] = int(v) if v.isdigit() else v
        elif k.startswith("receive rate"):
            info["rx_rate"] = _num(v)
        elif k.startswith("transmit rate"):
            info["tx_rate"] = _num(v)
        elif k == "signal":
            info["signal"] = _num(v.rstrip("%"))
        elif k == "authentication":
            info["auth"] = v
        elif k == "rssi":
            info["rssi"] = _num(v)
    if not info:
        return None
    info["connected"] = info.get("state", "").lower() == "connected"
    if "band" not in info and isinstance(info.get("channel"), int):
        ch = info["channel"]
        info["band"] = "2.4 GHz" if ch <= 14 else ("5 GHz" if ch < 180 else "6 GHz")
    if "rssi" not in info and info.get("signal") is not None:
        info["rssi"] = round(info["signal"] / 2 - 100)
    return info


def wifi_networks():
    if not IS_WINDOWS:
        return []
    out = run_cmd(["netsh", "wlan", "show", "networks", "mode=bssid"], timeout=15)
    nets, ssid, auth, cur = [], "", "", None
    for line in out.splitlines():
        s = line.strip()
        m = re.match(r"SSID \d+\s*:\s*(.*)", s)
        if m:
            ssid, auth = m.group(1).strip(), ""
            continue
        if ":" not in s:
            continue
        k, _, v = s.partition(":")
        k, v = k.strip().lower(), v.strip()
        if k.startswith("authentication"):
            auth = v
        elif k.startswith("bssid"):
            cur = {"ssid": ssid or "(hidden)", "bssid": v.upper(), "auth": auth}
            nets.append(cur)
        elif cur is not None:
            if k == "signal":
                cur["signal"] = _num(v.rstrip("%"))
            elif k == "channel":
                cur["channel"] = int(v) if v.isdigit() else None
            elif k == "band":
                cur["band"] = v
            elif k == "radio type":
                cur["radio"] = v
    for n in nets:
        ch = n.get("channel")
        if "band" not in n and isinstance(ch, int):
            n["band"] = "2.4 GHz" if ch <= 14 else "5 GHz"
    return nets


def _num(v):
    try:
        return float(re.findall(r"[\d.]+", v)[0])
    except (IndexError, ValueError):
        return None
