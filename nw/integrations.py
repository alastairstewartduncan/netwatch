"""Integrations: MQTT / Home Assistant, Pi-hole / AdGuard Home, SNMP (printers, NAS), the Claude-powered
"Ask NetWatch" assistant, GitHub auto-update and multi-site reporting."""

import base64
import json
import os
import re
import socket
import struct
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request

from .netops import USER_AGENT


def _http_json(url, data=None, headers=None, timeout=10, method=None):
    body = json.dumps(data).encode() if isinstance(data, (dict, list)) else data
    h = {"User-Agent": USER_AGENT, **(headers or {})}
    if isinstance(data, (dict, list)):
        h.setdefault("Content-Type", "application/json")
    req = urllib.request.Request(url, data=body, headers=h, method=method)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        raw = r.read()
    return json.loads(raw.decode() or "null")


# --------------------------------------------------------------------------- #
# Minimal MQTT 3.1.1 client (publish only) + Home Assistant discovery
# --------------------------------------------------------------------------- #

def _mqtt_str(s):
    b = s.encode("utf-8")
    return struct.pack("!H", len(b)) + b


def _mqtt_len(n):
    out = b""
    while True:
        byte = n % 128
        n //= 128
        out += bytes([byte | (0x80 if n else 0)])
        if not n:
            return out


class MQTTClient:
    def __init__(self, host, port=1883, username="", password="", client_id="netwatch", keepalive=60):
        self.host, self.port = host, int(port or 1883)
        self.username, self.password = username, password
        self.client_id, self.keepalive = client_id, keepalive
        self.sock = None
        self.lock = threading.RLock()
        self.last_io = 0

    def connect(self):
        s = socket.create_connection((self.host, self.port), timeout=8)
        flags = 0x02
        payload = _mqtt_str(self.client_id)
        will_topic = f"netwatch/{self.client_id}/availability"
        flags |= 0x04 | 0x20  # will flag + will retain, QoS 0
        payload += _mqtt_str(will_topic) + _mqtt_str("offline")
        if self.username:
            flags |= 0x80
            payload += _mqtt_str(self.username)
            if self.password:
                flags |= 0x40
                payload += _mqtt_str(self.password)
        var = _mqtt_str("MQTT") + bytes([4, flags]) + struct.pack("!H", self.keepalive)
        pkt = bytes([0x10]) + _mqtt_len(len(var) + len(payload)) + var + payload
        s.sendall(pkt)
        resp = s.recv(4)
        if len(resp) < 4 or resp[0] != 0x20 or resp[3] != 0:
            s.close()
            codes = {1: "bad protocol", 2: "client id rejected", 3: "broker unavailable",
                     4: "bad username or password", 5: "not authorised"}
            raise RuntimeError(f"MQTT connection refused ({codes.get(resp[3] if len(resp) > 3 else -1, 'unknown')})")
        s.settimeout(10)
        self.sock = s
        self.last_io = time.time()
        self.publish(will_topic, "online", retain=True)

    def publish(self, topic, payload, retain=False):
        with self.lock:
            if self.sock is None:
                self.connect()
            data = payload if isinstance(payload, bytes) else str(payload).encode()
            var = _mqtt_str(topic)
            pkt = bytes([0x30 | (0x01 if retain else 0)]) + _mqtt_len(len(var) + len(data)) + var + data
            try:
                self.sock.sendall(pkt)
                self.last_io = time.time()
            except OSError:
                self.close()
                raise

    def ping(self):
        with self.lock:
            if self.sock and time.time() - self.last_io > self.keepalive / 2:
                try:
                    self.sock.sendall(b"\xc0\x00")
                    self.last_io = time.time()
                except OSError:
                    self.close()

    def close(self):
        try:
            if self.sock:
                self.sock.sendall(b"\xe0\x00")
                self.sock.close()
        except OSError:
            pass
        self.sock = None


HA_SENSORS = [
    ("latency", "Latency", "ms", None, "mdi:timer-outline"),
    ("jitter", "Jitter", "ms", None, "mdi:chart-bell-curve"),
    ("loss", "Packet loss", "%", None, "mdi:package-variant-remove"),
    ("download", "Download", "Mbit/s", "data_rate", "mdi:download"),
    ("upload", "Upload", "Mbit/s", "data_rate", "mdi:upload"),
    ("devices_online", "Devices online", None, None, "mdi:devices"),
    ("wifi_signal", "Wi-Fi signal", "%", None, "mdi:wifi"),
    ("dns_ms", "DNS lookup", "ms", None, "mdi:dns"),
    ("speed_down", "Speed test download", "Mbit/s", "data_rate", "mdi:speedometer"),
    ("speed_up", "Speed test upload", "Mbit/s", "data_rate", "mdi:speedometer"),
    ("call_quality", "Call quality (MOS)", None, None, "mdi:phone-in-talk"),
    ("status", "Status", None, None, "mdi:shield-check"),
    ("public_ip", "Public IP", None, None, "mdi:ip-network"),
]


class HomeAssistantBridge:
    def __init__(self, get_cfg):
        self.get_cfg = get_cfg
        self.client = None
        self._sig = None
        self._announced = set()
        self.state = {"connected": False, "error": None, "last": 0}
        self.node = re.sub(r"[^a-z0-9_]", "_", socket.gethostname().lower())

    def _ensure(self):
        cfg = self.get_cfg()
        sig = (cfg.get("mqtt_host"), cfg.get("mqtt_port"), cfg.get("mqtt_user"), cfg.get("mqtt_password"))
        if self.client is None or sig != self._sig:
            if self.client:
                self.client.close()
            from .winapi import unprotect
            self.client = MQTTClient(cfg["mqtt_host"], cfg.get("mqtt_port") or 1883, cfg.get("mqtt_user", ""),
                                     unprotect(cfg.get("mqtt_password", "")), client_id=f"netwatch_{self.node}")
            self._sig = sig
            self._announced = set()
        return self.client

    def _device(self):
        return {"identifiers": [f"netwatch_{self.node}"], "name": f"NetWatch ({socket.gethostname()})",
                "manufacturer": "NetWatch", "model": "Network monitor"}

    def publish(self, values, presence):
        cfg = self.get_cfg()
        prefix = cfg.get("mqtt_discovery_prefix") or "homeassistant"
        base = f"netwatch/{self.node}"
        c = self._ensure()
        try:
            if "core" not in self._announced:
                for key, name, unit, dclass, icon in HA_SENSORS:
                    conf = {"name": name, "unique_id": f"netwatch_{self.node}_{key}", "state_topic": f"{base}/state",
                            "value_template": f"{{{{ value_json.{key} }}}}", "icon": icon, "device": self._device(),
                            "availability_topic": f"netwatch/netwatch_{self.node}/availability"}
                    if unit:
                        conf["unit_of_measurement"] = unit
                        conf["state_class"] = "measurement"
                    if dclass:
                        conf["device_class"] = dclass
                    c.publish(f"{prefix}/sensor/netwatch_{self.node}/{key}/config", json.dumps(conf), retain=True)
                conf = {"name": "Internet", "unique_id": f"netwatch_{self.node}_internet", "state_topic": f"{base}/state",
                        "value_template": "{{ 'ON' if value_json.internet else 'OFF' }}", "device_class": "connectivity",
                        "device": self._device(), "availability_topic": f"netwatch/netwatch_{self.node}/availability"}
                c.publish(f"{prefix}/binary_sensor/netwatch_{self.node}/internet/config", json.dumps(conf), retain=True)
                self._announced.add("core")
            for key, (label, online) in presence.items():
                obj = re.sub(r"[^a-z0-9_]", "_", key.lower())
                if obj not in self._announced:
                    conf = {"name": f"{label} home", "unique_id": f"netwatch_{self.node}_dev_{obj}",
                            "state_topic": f"{base}/device/{obj}", "device_class": "presence", "device": self._device(),
                            "payload_on": "ON", "payload_off": "OFF"}
                    c.publish(f"{prefix}/binary_sensor/netwatch_{self.node}/dev_{obj}/config", json.dumps(conf),
                              retain=True)
                    self._announced.add(obj)
                c.publish(f"{base}/device/{obj}", "ON" if online else "OFF", retain=True)
            c.publish(f"{base}/state", json.dumps(values), retain=True)
            c.ping()
            self.state = {"connected": True, "error": None, "last": time.time()}
        except Exception as e:
            self.state = {"connected": False, "error": str(e), "last": self.state.get("last", 0)}
            if self.client:
                self.client.close()

    def stop(self):
        if self.client:
            self.client.close()


# --------------------------------------------------------------------------- #
# Pi-hole / AdGuard Home
# --------------------------------------------------------------------------- #

class DnsFilter:
    def __init__(self, get_cfg):
        self.get_cfg = get_cfg
        self._sid = None

    def stats(self):
        cfg = self.get_cfg()
        kind = cfg.get("dnsfilter_type", "pihole")
        url = (cfg.get("dnsfilter_url") or "").rstrip("/")
        if not url:
            return {"enabled": False}
        if not re.match(r"https?://", url):
            url = "http://" + url
        from .winapi import unprotect
        secret = unprotect(cfg.get("dnsfilter_password", ""))
        try:
            if kind == "adguard":
                return self._adguard(url, cfg.get("dnsfilter_user", ""), secret)
            return self._pihole(url, secret)
        except Exception as e:
            return {"enabled": True, "error": str(e)}

    def _pihole(self, url, password):
        try:  # Pi-hole v6
            if not self._sid:
                auth = _http_json(f"{url}/api/auth", {"password": password})
                self._sid = (auth.get("session") or {}).get("sid")
            q = f"sid={urllib.parse.quote(self._sid or '')}"
            summ = _http_json(f"{url}/api/stats/summary?{q}")
            blocked = _http_json(f"{url}/api/stats/top_domains?blocked=true&count=10&{q}")
            clients = _http_json(f"{url}/api/stats/top_clients?count=10&{q}")
            qs = summ.get("queries", {})
            return {"enabled": True, "kind": "Pi-hole", "queries": qs.get("total"), "blocked": qs.get("blocked"),
                    "percent": qs.get("percent_blocked"), "domains_on_list": (summ.get("gravity") or {}).get("domains_being_blocked"),
                    "top_blocked": [{"domain": d.get("domain"), "count": d.get("count")} for d in blocked.get("domains", [])],
                    "top_clients": [{"name": c.get("name") or c.get("ip"), "ip": c.get("ip"), "count": c.get("count")}
                                    for c in clients.get("clients", [])]}
        except urllib.error.HTTPError as e:
            self._sid = None
            if e.code not in (404, 401):
                raise
            if e.code == 401:
                raise RuntimeError("Pi-hole rejected the password")
        # Pi-hole v5 (token = API token from Settings → API)
        tok = urllib.parse.quote(password)
        summ = _http_json(f"{url}/admin/api.php?summaryRaw&auth={tok}")
        top = _http_json(f"{url}/admin/api.php?topItems=10&auth={tok}")
        src = _http_json(f"{url}/admin/api.php?getQuerySources=10&auth={tok}")
        return {"enabled": True, "kind": "Pi-hole", "queries": summ.get("dns_queries_today"),
                "blocked": summ.get("ads_blocked_today"), "percent": summ.get("ads_percentage_today"),
                "domains_on_list": summ.get("domains_being_blocked"),
                "top_blocked": [{"domain": d, "count": c} for d, c in (top.get("top_ads") or {}).items()],
                "top_clients": [{"name": k.split("|")[0], "ip": k.split("|")[-1], "count": v}
                                for k, v in (src.get("top_sources") or {}).items()]}

    def _adguard(self, url, user, password):
        auth = base64.b64encode(f"{user}:{password}".encode()).decode()
        h = {"Authorization": f"Basic {auth}"}
        st = _http_json(f"{url}/control/stats", headers=h)
        total = st.get("num_dns_queries") or 0
        blocked = st.get("num_blocked_filtering") or 0

        def flat(items):
            out = []
            for d in items or []:
                for k, v in d.items():
                    out.append((k, v))
            return out
        return {"enabled": True, "kind": "AdGuard Home", "queries": total, "blocked": blocked,
                "percent": 100 * blocked / total if total else 0, "domains_on_list": None,
                "top_blocked": [{"domain": k, "count": v} for k, v in flat(st.get("top_blocked_domains"))[:10]],
                "top_clients": [{"name": k, "ip": k, "count": v} for k, v in flat(st.get("top_clients"))[:10]]}


# --------------------------------------------------------------------------- #
# SNMP v2c (GET / GETNEXT walk) for printers & NAS
# --------------------------------------------------------------------------- #

def _ber_len(n):
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag, value):
    return bytes([tag]) + _ber_len(len(value)) + value


def _ber_int(n):
    return _tlv(0x02, n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big", signed=True))


def _ber_oid(oid):
    parts = [int(x) for x in oid.strip(".").split(".")]
    body = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        enc = [p & 0x7F]
        p >>= 7
        while p:
            enc.insert(0, 0x80 | (p & 0x7F))
            p >>= 7
        body += bytes(enc)
    return _tlv(0x06, body)


def _parse(data, i=0):
    tag = data[i]
    ln = data[i + 1]
    i += 2
    if ln & 0x80:
        nb = ln & 0x7F
        ln = int.from_bytes(data[i:i + nb], "big")
        i += nb
    return tag, data[i:i + ln], i + ln


def _parse_seq(body):
    out, i = [], 0
    while i < len(body):
        tag, val, i = _parse(body, i)
        out.append((tag, val))
    return out


def _decode_oid(b):
    first = b[0]
    parts = [first // 40, first % 40]
    n = 0
    for byte in b[1:]:
        n = (n << 7) | (byte & 0x7F)
        if not byte & 0x80:
            parts.append(n)
            n = 0
    return ".".join(map(str, parts))


def _decode_value(tag, val):
    if tag in (0x02, 0x41, 0x42, 0x43, 0x46):
        return int.from_bytes(val, "big", signed=(tag == 0x02))
    if tag == 0x04:
        try:
            return val.decode("utf-8").strip("\x00")
        except UnicodeDecodeError:
            return val.hex(":")
    if tag == 0x06:
        return _decode_oid(val)
    if tag == 0x40:
        return ".".join(str(x) for x in val)
    return None  # null / noSuchObject / endOfMibView


def snmp_request(host, community, oid, pdu_type=0xA0, timeout=2.0, retries=1):
    rid = int.from_bytes(os.urandom(3), "big")
    varbind = _tlv(0x30, _ber_oid(oid) + b"\x05\x00")
    pdu = _tlv(pdu_type, _ber_int(rid) + _ber_int(0) + _ber_int(0) + _tlv(0x30, varbind))
    msg = _tlv(0x30, _ber_int(1) + _tlv(0x04, community.encode()) + pdu)
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.settimeout(timeout)
    try:
        for _ in range(retries + 1):
            s.sendto(msg, (host, 161))
            try:
                data, _ = s.recvfrom(65535)
            except socket.timeout:
                continue
            _, body, _ = _parse(data)
            items = _parse_seq(body)
            pdu_tag, pdu_body = items[2]
            fields = _parse_seq(pdu_body)
            if int.from_bytes(fields[1][1], "big"):
                return None
            vbs = _parse_seq(fields[3][1])
            _, vb = vbs[0]
            (otag, oval), (vtag, vval) = _parse_seq(vb)
            return _decode_oid(oval), vtag, _decode_value(vtag, vval)
    finally:
        s.close()
    raise TimeoutError("No SNMP response (check the device has SNMP enabled and the community name)")


def snmp_get(host, community, oid):
    r = snmp_request(host, community, oid, 0xA0)
    return None if not r or r[1] in (0x80, 0x81, 0x82) else r[2]


def snmp_walk(host, community, prefix, limit=64):
    out, oid = [], prefix
    for _ in range(limit):
        r = snmp_request(host, community, oid, 0xA1)
        if not r or not r[0].startswith(prefix + ".") or r[1] in (0x80, 0x81, 0x82):
            break
        out.append((r[0], r[2]))
        oid = r[0]
    return out


def snmp_health(host, community="public"):
    info = {"host": host, "name": snmp_get(host, community, "1.3.6.1.2.1.1.5.0"),
            "description": snmp_get(host, community, "1.3.6.1.2.1.1.1.0")}
    up = snmp_get(host, community, "1.3.6.1.2.1.1.3.0")
    info["uptime_s"] = up / 100 if isinstance(up, int) else None
    # printer supplies (Printer-MIB)
    desc = snmp_walk(host, community, "1.3.6.1.2.1.43.11.1.1.6")
    if desc:
        maxc = dict(snmp_walk(host, community, "1.3.6.1.2.1.43.11.1.1.8"))
        lvl = dict(snmp_walk(host, community, "1.3.6.1.2.1.43.11.1.1.9"))
        sup = []
        for oid, name in desc:
            idx = oid.split(".")[-2:]
            mo = "1.3.6.1.2.1.43.11.1.1.8." + ".".join(idx)
            lo = "1.3.6.1.2.1.43.11.1.1.9." + ".".join(idx)
            m, l = maxc.get(mo), lvl.get(lo)
            pct = round(100 * l / m) if isinstance(m, int) and isinstance(l, int) and m > 0 and l >= 0 else None
            sup.append({"name": name, "percent": pct, "level": l, "max": m})
        info["supplies"] = sup
    # Synology disks
    temps = snmp_walk(host, community, "1.3.6.1.4.1.6574.2.1.1.6")
    if temps:
        names = dict(snmp_walk(host, community, "1.3.6.1.4.1.6574.2.1.1.2"))
        status = dict(snmp_walk(host, community, "1.3.6.1.4.1.6574.2.1.1.5"))
        stmap = {1: "Normal", 2: "Initialized", 3: "Not initialized", 4: "System partition failed", 5: "Crashed"}
        info["disks"] = [{"name": names.get(o.replace(".6.", ".2.", 1), o.split(".")[-1]), "temp_c": t,
                          "status": stmap.get(status.get(o.replace(".6.", ".5.", 1)), "")} for o, t in temps]
        info["system_temp_c"] = snmp_get(host, community, "1.3.6.1.4.1.6574.1.2.0")
    # Storage usage (HOST-RESOURCES-MIB)
    sdesc = snmp_walk(host, community, "1.3.6.1.2.1.25.2.3.1.3", limit=40)
    if sdesc:
        units = dict(snmp_walk(host, community, "1.3.6.1.2.1.25.2.3.1.4", limit=40))
        size = dict(snmp_walk(host, community, "1.3.6.1.2.1.25.2.3.1.5", limit=40))
        used = dict(snmp_walk(host, community, "1.3.6.1.2.1.25.2.3.1.6", limit=40))
        vols = []
        for oid, name in sdesc:
            idx = oid.split(".")[-1]
            u = units.get(f"1.3.6.1.2.1.25.2.3.1.4.{idx}") or 1
            sz = size.get(f"1.3.6.1.2.1.25.2.3.1.5.{idx}") or 0
            us = used.get(f"1.3.6.1.2.1.25.2.3.1.6.{idx}") or 0
            if sz and isinstance(name, str) and (name.startswith("/volume") or re.match(r"^[A-Z]:\\", name)
                                                 or name in ("/", "/data")):
                vols.append({"name": name, "total": sz * u, "used": us * u, "percent": round(100 * us / sz, 1)})
        if vols:
            info["volumes"] = vols
    return info


# --------------------------------------------------------------------------- #
# "Ask NetWatch" (Claude API)
# --------------------------------------------------------------------------- #

ASSISTANT_SYSTEM = (
    "You are NetWatch's built-in network assistant. You help a home or small-office user understand their "
    "internet connection and home network. You are given a JSON snapshot of the monitoring data NetWatch has "
    "collected. Answer in plain English, be specific with numbers and times from the data, keep answers short "
    "(a few sentences or a brief list), say clearly when the data doesn't show something, and suggest practical "
    "next steps (e.g. restart router, move closer to Wi-Fi, contact ISP with the report). Never invent data.")


def ask_claude(api_key, model, question, context, history=None):
    if not api_key:
        raise RuntimeError("Add your Anthropic API key in Settings → Integrations to use the assistant.")
    messages = []
    for h in (history or [])[-8:]:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": f"Monitoring data (JSON):\n{json.dumps(context, default=str)[:60000]}"
                                                 f"\n\nQuestion: {question}"})
    body = {"model": model or "claude-sonnet-5-5", "max_tokens": 1200, "system": ASSISTANT_SYSTEM,
            "messages": messages}
    try:
        res = _http_json("https://api.anthropic.com/v1/messages", body, timeout=90,
                         headers={"x-api-key": api_key, "anthropic-version": "2023-06-01"})
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors="ignore")[:300]
        raise RuntimeError(f"Claude API error {e.code}: {detail}")
    return "".join(b.get("text", "") for b in res.get("content", []) if b.get("type") == "text").strip()


# --------------------------------------------------------------------------- #
# Auto-update from GitHub releases
# --------------------------------------------------------------------------- #

def _ver(v):
    return tuple(int(x) for x in re.findall(r"\d+", v or "0")[:3]) or (0,)


class Updater:
    def __init__(self, data_dir, current_version):
        self.dir = data_dir / "update"
        self.current = current_version
        self.state = {"checked": 0, "latest": None, "available": False, "downloaded": None, "error": None,
                      "notes": "", "url": None}

    def check(self, repo):
        if not repo or "/" not in repo:
            self.state["error"] = "Set a GitHub repository (owner/name) in Settings."
            return self.state
        try:
            rel = _http_json(f"https://api.github.com/repos/{repo}/releases/latest",
                             headers={"Accept": "application/vnd.github+json"})
            tag = rel.get("tag_name", "")
            exes = [a for a in rel.get("assets", []) if a.get("name", "").lower().endswith(".exe")]
            # Prefer the installer (works for standard users, upgrades in place); fall back to a bare exe
            asset = next((a for a in exes if "setup" in a["name"].lower()), exes[0] if exes else None)
            self.state.update(checked=time.time(), latest=tag, notes=(rel.get("body") or "")[:4000],
                              available=_ver(tag) > _ver(self.current) and asset is not None,
                              installer=bool(asset and "setup" in asset["name"].lower()),
                              size=asset.get("size") if asset else None,
                              url=asset.get("browser_download_url") if asset else None, error=None)
        except Exception as e:
            self.state.update(checked=time.time(), error=f"Update check failed: {e}")
        return self.state

    def download(self):
        if not self.state.get("url"):
            raise RuntimeError("No update available")
        self.dir.mkdir(parents=True, exist_ok=True)
        dest = self.dir / ("NetWatch-Setup.exe" if self.state.get("installer") else "NetWatch-new.exe")
        req = urllib.request.Request(self.state["url"], headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=300) as r, open(dest, "wb") as fh:
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                fh.write(chunk)
        if dest.stat().st_size < 1_000_000:
            raise RuntimeError("Downloaded file looks too small - update aborted")
        self.state["downloaded"] = str(dest)
        return str(dest)

    def apply_and_restart(self):
        """Runs the downloaded installer silently (it closes NetWatch, upgrades and relaunches it).
        For a bare exe (portable copies), swaps the running exe via a tiny batch script instead."""
        if not getattr(sys, "frozen", False):
            raise RuntimeError("Updates can only be applied to the packaged NetWatch app")
        new = self.state.get("downloaded")
        if not new or not os.path.exists(new):
            raise RuntimeError("Download the update first")
        if self.state.get("installer"):
            import ctypes
            # "runas" shows a single UAC prompt; /S = silent, /UPDATE = relaunch NetWatch when done
            rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", new, "/S /UPDATE", None, 1)
            if rc <= 32:
                raise RuntimeError("The update was cancelled")
            return True
        exe = sys.executable
        bat = self.dir / "apply-update.bat"
        bat.write_text(
            "@echo off\r\n"
            f"set PID={os.getpid()}\r\n"
            ":wait\r\n"
            'tasklist /FI "PID eq %PID%" | find "%PID%" >nul && (timeout /t 1 >nul & goto wait)\r\n'
            f'copy /Y "{new}" "{exe}" >nul\r\n'
            f'start "" "{exe}"\r\n'
            'del "%~f0"\r\n', encoding="utf-8")
        subprocess.Popen(["cmd", "/c", str(bat)], creationflags=0x08000000 | 0x00000008)
        return True


# --------------------------------------------------------------------------- #
# Multi-site: agents push summaries to a hub
# --------------------------------------------------------------------------- #

def push_site_report(hub_url, key, report):
    url = hub_url.rstrip("/")
    if not re.match(r"https?://", url):
        url = "http://" + url
    return _http_json(f"{url}/site/report", report, headers={"X-NW-Site-Key": key}, timeout=10)
