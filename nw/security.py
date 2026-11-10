"""Security features: router port-forward audit (UPnP), exposure lookup, spoofing / rogue DHCP checks,
this-PC security review, firewall app blocking, packet capture, captive portal and code signatures."""

import http.client
import ipaddress
import json
import os
import random
import re
import socket
import struct
import threading
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from . import winapi
from .netops import COMMON_PORTS, RISKY_PORTS, USER_AGENT
from .winapi import IS_WINDOWS, run_cmd

try:
    import psutil
except ImportError:
    psutil = None


# --------------------------------------------------------------------------- #
# UPnP Internet Gateway Device
# --------------------------------------------------------------------------- #

SSDP_ADDR = ("239.255.255.250", 1900)
IGD_TARGETS = ["urn:schemas-upnp-org:device:InternetGatewayDevice:1",
               "urn:schemas-upnp-org:device:InternetGatewayDevice:2",
               "urn:schemas-upnp-org:service:WANIPConnection:1"]


def ssdp_discover(timeout=3.0):
    locations = []
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
    s.settimeout(0.5)
    s.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
    try:
        for st in IGD_TARGETS:
            msg = (f"M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\n"
                   f"MX: 2\r\nST: {st}\r\n\r\n").encode()
            s.sendto(msg, SSDP_ADDR)
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(4096)
            except socket.timeout:
                continue
            m = re.search(rb"(?im)^location:\s*(\S+)", data)
            if m:
                loc = m.group(1).decode(errors="ignore")
                if loc not in locations:
                    locations.append(loc)
    except OSError:
        pass
    finally:
        s.close()
    return locations


def _fetch(url, timeout=5, limit=300_000):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(limit)


def _strip_ns(tag):
    return tag.split("}", 1)[-1]


def igd_services(location):
    root = ET.fromstring(_fetch(location))
    base = location
    out = {"location": location, "name": "", "model": "", "services": {}}
    for el in root.iter():
        t = _strip_ns(el.tag)
        if t == "URLBase" and el.text:
            base = el.text.strip()
        elif t == "friendlyName" and not out["name"]:
            out["name"] = (el.text or "").strip()
        elif t == "modelName" and not out["model"]:
            out["model"] = (el.text or "").strip()
        elif t == "service":
            st = ctrl = None
            for c in el:
                ct = _strip_ns(c.tag)
                if ct == "serviceType":
                    st = (c.text or "").strip()
                elif ct == "controlURL":
                    ctrl = (c.text or "").strip()
            if st and ctrl:
                out["services"][st] = urllib.parse.urljoin(base, ctrl)
    return out


def soap_call(control_url, service_type, action, args=None, timeout=5):
    args = args or {}
    body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    envelope = (f'<?xml version="1.0"?><s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/" '
                f's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/"><s:Body>'
                f'<u:{action} xmlns:u="{service_type}">{body}</u:{action}></s:Body></s:Envelope>').encode()
    u = urllib.parse.urlparse(control_url)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=timeout)
    try:
        conn.request("POST", u.path or "/", envelope, {
            "Content-Type": 'text/xml; charset="utf-8"', "SOAPAction": f'"{service_type}#{action}"',
            "User-Agent": USER_AGENT})
        resp = conn.getresponse()
        data = resp.read(200_000)
        if resp.status != 200:
            return None
        root = ET.fromstring(data)
        out = {}
        for el in root.iter():
            if len(el) == 0 and el.text is not None:
                out[_strip_ns(el.tag)] = el.text.strip()
        return out
    finally:
        conn.close()


def upnp_audit():
    """Returns router info + every port forward the router has open (UPnP)."""
    locs = ssdp_discover()
    if not locs:
        return {"found": False, "mappings": [], "note": "No UPnP router answered. UPnP is either switched off "
                "(good for security) or blocked on this network."}
    for loc in locs:
        try:
            dev = igd_services(loc)
        except Exception:
            continue
        wan = next(((st, url) for st, url in dev["services"].items()
                    if "WANIPConnection" in st or "WANPPPConnection" in st), None)
        if not wan:
            continue
        st, url = wan
        result = {"found": True, "router": dev["name"] or dev["model"], "model": dev["model"],
                  "location": loc, "mappings": [], "external_ip": None, "wan_rx": None, "wan_tx": None}
        try:
            r = soap_call(url, st, "GetExternalIPAddress")
            result["external_ip"] = (r or {}).get("NewExternalIPAddress")
        except Exception:
            pass
        for i in range(256):
            try:
                r = soap_call(url, st, "GetGenericPortMappingEntry", {"NewPortMappingIndex": i})
            except Exception:
                r = None
            if not r or "NewExternalPort" not in r:
                break
            port = int(r.get("NewExternalPort") or 0)
            result["mappings"].append({
                "external_port": port, "protocol": r.get("NewProtocol", ""),
                "internal_client": r.get("NewInternalClient", ""), "internal_port": int(r.get("NewInternalPort") or 0),
                "description": r.get("NewPortMappingDescription", ""),
                "enabled": r.get("NewEnabled", "1") in ("1", "true"),
                "lease": int(r.get("NewLeaseDuration") or 0), "remote_host": r.get("NewRemoteHost", ""),
                "service": COMMON_PORTS.get(port, ""), "risky": port in RISKY_PORTS})
        cic = next((u for s2, u in dev["services"].items() if "WANCommonInterfaceConfig" in s2), None)
        if cic:
            cst = next(s2 for s2 in dev["services"] if "WANCommonInterfaceConfig" in s2)
            try:
                rx = soap_call(cic, cst, "GetTotalBytesReceived") or {}
                tx = soap_call(cic, cst, "GetTotalBytesSent") or {}
                result["wan_rx"] = int(rx.get("NewTotalBytesReceived") or 0) or None
                result["wan_tx"] = int(tx.get("NewTotalBytesSent") or 0) or None
            except Exception:
                pass
        return result
    return {"found": False, "mappings": [], "note": "A UPnP device answered but it doesn't offer port forwarding."}


# --------------------------------------------------------------------------- #
# Internet exposure (Shodan InternetDB - free, no key)
# --------------------------------------------------------------------------- #

def exposure_check(public_ip):
    if not public_ip:
        return {"error": "Public IP not known yet"}
    try:
        data = json.loads(_fetch(f"https://internetdb.shodan.io/{public_ip}", timeout=10))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ip": public_ip, "ports": [], "vulns": [], "hostnames": [], "tags": [], "clean": True}
        return {"error": f"Lookup failed (HTTP {e.code})"}
    except Exception as e:
        return {"error": f"Lookup failed: {e}"}
    ports = data.get("ports", [])
    return {"ip": public_ip, "ports": [{"port": p, "service": COMMON_PORTS.get(p, ""), "risky": p in RISKY_PORTS}
                                       for p in ports],
            "vulns": data.get("vulns", [])[:50], "hostnames": data.get("hostnames", []),
            "tags": data.get("tags", []), "cpes": data.get("cpes", []), "clean": not ports}


# --------------------------------------------------------------------------- #
# ARP spoofing & rogue DHCP
# --------------------------------------------------------------------------- #

def arp_spoof_check(arp_table, gateway):
    """Other IPs sharing the router's MAC address suggest ARP spoofing (man-in-the-middle)."""
    gw_mac = arp_table.get(gateway or "")
    if not gw_mac:
        return {"gateway_mac": None, "shared_with": []}
    shared = [ip for ip, mac in arp_table.items() if mac == gw_mac and ip != gateway]
    return {"gateway_mac": gw_mac, "shared_with": shared}


def dhcp_discover(mac, timeout=4.0):
    """Broadcasts a DHCPDISCOVER and lists every server that answers. More than one = rogue DHCP server."""
    xid = random.randint(0, 0xFFFFFFFF)
    chaddr = bytes.fromhex(re.sub(r"[^0-9A-Fa-f]", "", mac or "02:00:00:00:00:01")[:12]).ljust(16, b"\x00")
    pkt = struct.pack("!BBBBIHH4s4s4s4s", 1, 1, 6, 0, xid, 0, 0x8000, b"\0" * 4, b"\0" * 4, b"\0" * 4, b"\0" * 4)
    pkt += chaddr + b"\0" * 192 + b"\x63\x82\x53\x63"
    pkt += b"\x35\x01\x01" + b"\x37\x04\x01\x03\x06\x0f" + b"\xff"
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.bind(("", 68))
    except OSError as e:
        s.close()
        return {"error": f"Couldn't listen for DHCP replies ({e}). Try running as administrator."}
    servers = {}
    try:
        s.settimeout(0.5)
        s.sendto(pkt, ("255.255.255.255", 67))
        end = time.time() + timeout
        while time.time() < end:
            try:
                data, addr = s.recvfrom(2048)
            except socket.timeout:
                continue
            if len(data) < 240 or data[0] != 2 or struct.unpack("!I", data[4:8])[0] != xid:
                continue
            offered = socket.inet_ntoa(data[16:20])
            server = addr[0]
            i = 240
            while i < len(data) and data[i] != 255:
                if data[i] == 0:
                    i += 1
                    continue
                code, ln = data[i], data[i + 1]
                if code == 54 and ln == 4:
                    server = socket.inet_ntoa(data[i + 2:i + 6])
                i += 2 + ln
            servers[server] = offered
    finally:
        s.close()
    return {"servers": [{"server": k, "offered": v} for k, v in servers.items()], "rogue": len(servers) > 1}


# --------------------------------------------------------------------------- #
# This-PC security review
# --------------------------------------------------------------------------- #

def _reg_value(root, path, name):
    try:
        import winreg
        with winreg.OpenKey(getattr(winreg, root), path) as k:
            return winreg.QueryValueEx(k, name)[0]
    except Exception:
        return None


def pc_security_check():
    checks = []

    def add(cid, title, status, detail, fix=None):
        checks.append({"id": cid, "title": title, "status": status, "detail": detail, "fix": fix})

    if IS_WINDOWS:
        fw = run_cmd(["netsh", "advfirewall", "show", "allprofiles", "state"])
        states = re.findall(r"(?im)^\s*State\s+(ON|OFF)", fw)
        if states:
            off = states.count("OFF")
            add("firewall", "Windows Firewall", "ok" if not off else "bad",
                "On for all network profiles" if not off else f"Off for {off} network profile(s)",
                None if not off else "Turn it back on in Windows Security → Firewall & network protection.")
        else:
            add("firewall", "Windows Firewall", "unknown", "Couldn't read firewall state")

        ps = run_cmd(["powershell", "-NoProfile", "-Command",
                      "$m=Get-MpComputerStatus -ErrorAction SilentlyContinue; $p=Get-NetConnectionProfile -ErrorAction SilentlyContinue;"
                      "@{rt=$m.RealTimeProtectionEnabled; age=$m.AntivirusSignatureAge; av=$m.AntivirusEnabled;"
                      "profiles=@($p | ForEach-Object { @{name=$_.Name; cat=[string]$_.NetworkCategory} })} | ConvertTo-Json -Depth 3"],
                     timeout=40)
        try:
            info = json.loads(ps) if ps.strip() else {}
        except ValueError:
            info = {}
        if info.get("rt") is not None:
            ok = info.get("rt") and (info.get("age") or 0) <= 3
            add("defender", "Antivirus (Microsoft Defender)", "ok" if ok else "warn",
                ("Real-time protection on" if info.get("rt") else "Real-time protection OFF") +
                (f" · signatures {info.get('age')} day(s) old" if info.get("age") is not None else ""),
                None if ok else "Open Windows Security and turn on real-time protection / check for updates.")
        else:
            add("defender", "Antivirus", "unknown", "Defender status unavailable (another antivirus may be in use)")
        profiles = info.get("profiles") or []
        if isinstance(profiles, dict):
            profiles = [profiles]
        for p in profiles:
            public = str(p.get("cat", "")).lower() == "public"
            add("profile", f"Network profile: {p.get('name', '')}", "ok" if public else "info",
                "Public (strictest - recommended on untrusted networks)" if public else
                f"{p.get('cat')} (sharing allowed - fine at home, risky on public Wi-Fi)")

        rdp = _reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Control\Terminal Server", "fDenyTSConnections")
        if rdp is not None:
            add("rdp", "Remote Desktop", "warn" if rdp == 0 else "ok",
                "Enabled - other machines can try to log in to this PC" if rdp == 0 else "Disabled",
                "Turn off in Settings → System → Remote Desktop if you don't use it." if rdp == 0 else None)
        smb1 = _reg_value("HKEY_LOCAL_MACHINE", r"SYSTEM\CurrentControlSet\Services\mrxsmb10", "Start")
        if smb1 is not None:
            add("smb1", "SMBv1 (legacy file sharing)", "bad" if smb1 != 4 else "ok",
                "Enabled - an outdated protocol exploited by WannaCry" if smb1 != 4 else "Disabled",
                "Turn off 'SMB 1.0/CIFS File Sharing Support' in Windows Features." if smb1 != 4 else None)
        else:
            add("smb1", "SMBv1 (legacy file sharing)", "ok", "Not installed")

    listening = []
    if psutil:
        seen = set()
        for c in psutil.net_connections(kind="inet"):
            if c.status != psutil.CONN_LISTEN or not c.laddr:
                continue
            if c.laddr.ip in ("127.0.0.1", "::1"):
                continue
            key = (c.laddr.port, c.pid)
            if key in seen:
                continue
            seen.add(key)
            try:
                name = psutil.Process(c.pid).name() if c.pid else "System"
            except Exception:
                name = "?"
            listening.append({"port": c.laddr.port, "address": c.laddr.ip, "process": name,
                              "service": COMMON_PORTS.get(c.laddr.port, ""), "risky": c.laddr.port in RISKY_PORTS})
        listening.sort(key=lambda x: x["port"])
        risky = [x for x in listening if x["risky"]]
        add("listening", "Services listening on the network", "warn" if risky else "ok",
            f"{len(listening)} open port(s)" + (f", including {', '.join(sorted({r['service'] for r in risky}))}"
                                                 if risky else ""),
            "Only a problem if your firewall lets them through - check the list below." if risky else None)

    weights = {"ok": 1, "info": 1, "warn": 0.5, "bad": 0, "unknown": 0.75}
    scored = [weights.get(c["status"], 1) for c in checks]
    score = round(100 * sum(scored) / len(scored)) if scored else None
    return {"checks": checks, "listening": listening, "score": score, "admin": winapi.is_admin()}


# --------------------------------------------------------------------------- #
# Firewall app blocking (requires admin)
# --------------------------------------------------------------------------- #

RULE_PREFIX = "NetWatch block - "


def _rule_name(path):
    return RULE_PREFIX + os.path.basename(path)


def block_app(path):
    if not IS_WINDOWS:
        raise RuntimeError("Windows only")
    if not winapi.is_admin():
        raise RuntimeError("Blocking apps needs administrator rights - restart NetWatch as administrator.")
    if not path or not os.path.exists(path):
        raise RuntimeError("Program file not found")
    name = _rule_name(path)
    for direction in ("out", "in"):
        out = run_cmd(["netsh", "advfirewall", "firewall", "add", "rule", f"name={name}", f"dir={direction}",
                       "action=block", f"program={path}", "enable=yes"])
        if "Ok" not in out and "ok" not in out.lower():
            raise RuntimeError(out.strip() or "netsh failed")
    return name


def unblock_app(path):
    if not winapi.is_admin():
        raise RuntimeError("Unblocking needs administrator rights.")
    run_cmd(["netsh", "advfirewall", "firewall", "delete", "rule", f"name={_rule_name(path)}"])
    return True


# --------------------------------------------------------------------------- #
# Packet capture (pktmon, built into Windows 10 2004+; requires admin)
# --------------------------------------------------------------------------- #

class Capture:
    def __init__(self, out_dir):
        self.out_dir = out_dir
        self.state = {"running": False, "seconds": 0, "elapsed": 0, "file": None, "error": None, "size": None}
        self._stop = False

    def start(self, seconds=60):
        if self.state["running"]:
            return False
        if not IS_WINDOWS:
            self.state["error"] = "Packet capture uses pktmon, which is Windows only."
            return False
        if not winapi.is_admin():
            self.state["error"] = "Packet capture needs administrator rights."
            return False
        self._stop = False
        self.state = {"running": True, "seconds": seconds, "elapsed": 0, "file": None, "error": None, "size": None}
        threading.Thread(target=self._run, args=(seconds,), daemon=True).start()
        return True

    def stop(self):
        self._stop = True

    def _run(self, seconds):
        self.out_dir.mkdir(parents=True, exist_ok=True)
        stamp = time.strftime("%Y%m%d-%H%M%S")
        etl = self.out_dir / f"capture-{stamp}.etl"
        pcap = self.out_dir / f"capture-{stamp}.pcapng"
        try:
            run_cmd(["pktmon", "filter", "remove"])
            out = run_cmd(["pktmon", "start", "--capture", "--pkt-size", "0", "--file-name", str(etl)])
            if "error" in out.lower() and "pktmon" not in out.lower():
                raise RuntimeError(out.strip())
            start = time.time()
            while time.time() - start < seconds and not self._stop:
                time.sleep(0.5)
                self.state["elapsed"] = time.time() - start
            run_cmd(["pktmon", "stop"], timeout=60)
            run_cmd(["pktmon", "etl2pcap", str(etl), "--out", str(pcap)], timeout=180)
            if pcap.exists():
                self.state["file"] = str(pcap)
                self.state["size"] = pcap.stat().st_size
                try:
                    etl.unlink()
                except OSError:
                    pass
            else:
                raise RuntimeError("pktmon didn't produce a capture file")
        except Exception as e:
            self.state["error"] = str(e)
            run_cmd(["pktmon", "stop"])
        finally:
            self.state["running"] = False


# --------------------------------------------------------------------------- #
# Captive portal / public Wi-Fi
# --------------------------------------------------------------------------- #

def captive_portal_check():
    """True if a login page is intercepting traffic (hotel / café Wi-Fi)."""
    try:
        conn = http.client.HTTPConnection("www.msftconnecttest.com", 80, timeout=6)
        conn.request("GET", "/connecttest.txt", headers={"User-Agent": USER_AGENT})
        r = conn.getresponse()
        body = r.read(200)
        conn.close()
        if r.status == 200 and body.strip() == b"Microsoft Connect Test":
            return {"portal": False}
        return {"portal": True, "status": r.status, "location": r.getheader("Location", "")}
    except Exception as e:
        return {"portal": None, "error": str(e)}


# --------------------------------------------------------------------------- #
# Code signature (Authenticode) of a program
# --------------------------------------------------------------------------- #

def signature(path):
    if not IS_WINDOWS or not path or not os.path.exists(path):
        return {"status": "unknown", "publisher": ""}
    p = path.replace("'", "''")
    out = run_cmd(["powershell", "-NoProfile", "-Command",
                   f"$s=Get-AuthenticodeSignature -LiteralPath '{p}'; "
                   f"@{{status=[string]$s.Status; subject=[string]$s.SignerCertificate.Subject}} | ConvertTo-Json"],
                  timeout=30)
    try:
        d = json.loads(out)
    except ValueError:
        return {"status": "unknown", "publisher": ""}
    subj = d.get("subject") or ""
    m = re.search(r"O=\"?([^,\"]+)", subj) or re.search(r"CN=\"?([^,\"]+)", subj)
    status = (d.get("status") or "").lower()
    return {"status": "signed" if status == "valid" else ("unsigned" if status == "notsigned" else status or "unknown"),
            "publisher": m.group(1).strip() if m else ""}
