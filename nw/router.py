"""Router integration: reads status straight from a TP-Link router's web admin API.

Uses the open-source `tplinkrouterc6u` library, which handles TP-Link's encrypted login. ISP-supplied
TP-Link routers (EX / VR / XDR / Archer / Deco families, e.g. the brsk EX820v) are supported to varying
degrees; anything the router doesn't answer is simply left out.

Design rules, because TP-Link routers only allow ONE admin session at a time:
  * every poll is log in -> read -> log out, as quickly as possible, never a held-open session
  * polls are infrequent (5 minutes by default) and never overlap
  * failed logins back off, and after 3 in a row polling stops until the settings change or the user
    presses Retry - so NetWatch can never lock the account by hammering a wrong password
  * read-only: NetWatch never changes router settings
"""

import json
import re
import threading
import time
from collections import deque

# OIDs tried for per-port Ethernet link status on EX-family firmware. Which one (if any) a firmware
# answers varies; the first that returns rows is remembered. tools/router_probe.py reports which works.
PORT_OIDS = ("DEV2_ETHERNET_IF", "DEV2_ETH_IF", "DEV2_ADT_ETH", "DEV2_ETH_INTF", "DEV2_ETHERNET_INTERFACE")
SECRET_KEY_HINTS = ("pass", "psk", "key", "secret", "token", "pin", "pwd")
EX_CLIENTS = ("TPLinkEXClientGCMOAEP", "TPLinkEXClientGCM", "TPLinkEXClient")
MAX_AUTH_FAILS = 3
HISTORY_POINTS = 7 * 24 * 12  # 7 days at 5-minute polls

BAND_LABEL = {"2G": "2.4 GHz", "5G": "5 GHz", "6G": "6 GHz"}


def _lib():
    try:
        import tplinkrouterc6u  # noqa: F401
        return tplinkrouterc6u
    except ImportError:
        raise RuntimeError("Router support isn't installed in this build (missing the tplinkrouterc6u package).")


def norm_mac(mac):
    return str(mac or "").replace("-", ":").upper()


def _scrub(obj):
    """Drops anything that looks like a password or key before data is shown or sent to the AI."""
    if isinstance(obj, dict):
        return {k: _scrub(v) for k, v in obj.items()
                if not any(h in str(k).lower() for h in SECRET_KEY_HINTS)}
    if isinstance(obj, list):
        return [_scrub(v) for v in obj]
    return obj


def _as_list(v):
    if v is None:
        return []
    return v if isinstance(v, list) else [v]


def _pick(d, *needles, exclude=()):
    """First value whose key contains one of `needles` (case-insensitive) and none of `exclude`."""
    for k, v in (d or {}).items():
        kl = k.lower()
        if any(n in kl for n in needles) and not any(x in kl for x in exclude) and v not in (None, ""):
            return v
    return None


def _speed_mbps(v):
    if v in (None, "", "-1"):
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*(g|m)?", str(v).lower())
    if not m:
        return None
    n = float(m.group(1))
    if m.group(2) == "g":
        n *= 1000
    return int(n) if n > 0 else None


def parse_ports(rows):
    """Turns raw Ethernet interface rows into [{name, up, speed_mbps, max_mbps, duplex}]."""
    ports = []
    for i, r in enumerate(_as_list(rows)):
        if not isinstance(r, dict):
            continue
        name = _pick(r, "name", "alias", exclude=("enable",)) or f"Port {i + 1}"
        status = str(_pick(r, "status", "link", exclude=("enable",)) or "").lower()
        up = True if status in ("up", "1", "connected", "linkup", "link up") else \
            False if status in ("down", "0", "disconnected", "nolink", "linkdown", "link down", "dormant") else None
        speed = _speed_mbps(_pick(r, "currentbitrate", "curbitrate", "speed", "rate", exclude=("max",)))
        maxs = _speed_mbps(_pick(r, "maxbitrate", "maxspeed"))
        if up is None and speed:
            up = True
        ports.append({"name": str(name), "up": up, "speed_mbps": speed if up else None, "max_mbps": maxs,
                      "duplex": _pick(r, "duplex")})
    return ports


def port_findings(ports):
    """Plain-English notes about ports linked below their capability (classically a faulty cable)."""
    notes = []
    for p in ports or []:
        if not p.get("up") or not p.get("speed_mbps"):
            continue
        cap = p.get("max_mbps") or 1000
        if p["speed_mbps"] < 1000 and cap >= 1000:
            notes.append(f"{p['name']} is linked at {p['speed_mbps']} Mbps on a {cap} Mbps port - usually a damaged or "
                         f"4-wire cable, or a device that only supports {p['speed_mbps']} Mbps.")
    return notes


def _conn_info(conn):
    """Maps the library's Connection enum to (kind, band label)."""
    name = getattr(conn, "name", str(conn)).upper()
    kind = "wired" if name == "WIRED" else "guest" if name.startswith("GUEST") else \
        "iot" if name.startswith("IOT") else "unknown" if name == "UNKNOWN" else "wifi"
    m = re.search(r"_(2G|5G|6G)", name)
    band = BAND_LABEL.get(m.group(1)) if m else ("Wi-Fi 7 MLO" if "MLO" in name else None)
    return kind, band


class RouterLink:
    def __init__(self, engine):
        self.e = engine
        self.path = engine.data_dir / "router_history.json"
        self.lock = threading.Lock()
        self.state = {"enabled": False, "running": False, "last_ok": 0, "last_try": 0, "error": None,
                      "auth_fails": 0, "suspended": False, "paused_until": 0, "client": None}
        self.snap = None
        self.history = deque(maxlen=HISTORY_POINTS)
        self._sig = None
        self._port_oid = None
        self._port_tried = False
        self._noted = set()
        self._load()

    # ------------------------------------------------------------------ persistence
    def _load(self):
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            self.history.extend(data.get("history", []))
            self.snap = data.get("last")
            self._port_oid = data.get("port_oid")
            self.state["client"] = data.get("client")
        except (OSError, ValueError):
            pass

    def _save(self):
        try:
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"history": list(self.history), "last": self.snap, "port_oid": self._port_oid,
                                       "client": self.state.get("client")}, default=str), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            self.e.log_error("router save")

    # ------------------------------------------------------------------ config
    def _cfg(self):
        s = self.e.settings
        from .winapi import unprotect
        host = (s.get("router_host") or "").strip() or (self.e.net or {}).get("gateway") or ""
        if host and not re.match(r"https?://", host):
            host = "http://" + host
        return {"enabled": bool(s.get("router_enabled")), "host": host.rstrip("/"),
                "user": (s.get("router_user") or "admin").strip(), "password": unprotect(s.get("router_password", "")),
                "interval": max(60, float(s.get("router_interval") or 300))}

    def _check_sig(self, cfg):
        sig = (cfg["host"], cfg["user"], cfg["password"])
        if sig != self._sig:
            if self._sig is not None:  # settings changed: forget the failure streak and the chosen client
                self.state.update(auth_fails=0, suspended=False, error=None)
                self.state["client"] = None
                self._port_oid, self._port_tried = None, False
            self._sig = sig

    def retry(self):
        self.state.update(auth_fails=0, suspended=False, error=None, paused_until=0)

    def pause(self, minutes):
        self.state["paused_until"] = time.time() + max(0, float(minutes)) * 60 if minutes else 0

    # ------------------------------------------------------------------ scheduling
    def tick(self):
        """Called every 30 s by the engine; polls when due."""
        cfg = self._cfg()
        self.state["enabled"] = cfg["enabled"]
        if not cfg["enabled"] or not cfg["password"] or not cfg["host"]:
            return
        self._check_sig(cfg)
        st = self.state
        if st["suspended"] or time.time() < st.get("paused_until", 0):
            return
        wait = cfg["interval"] * (2 ** min(st["auth_fails"], 3))
        if time.time() - st["last_try"] < wait:
            return
        self.poll()

    def poll(self, manual=False):
        cfg = self._cfg()
        if not cfg["password"]:
            raise RuntimeError("Enter the router's admin password in Settings → Integrations → Router.")
        if not cfg["host"]:
            raise RuntimeError("NetWatch hasn't found your router's address yet - enter it in Settings.")
        self._check_sig(cfg)
        if manual:
            self.state.update(suspended=False)
        if not self.lock.acquire(blocking=False):
            return self.snap
        self.state.update(running=True, last_try=time.time())
        try:
            snap = self._read(cfg)
        except Exception as ex:
            msg = str(ex)
            low = msg.lower()
            auth = ("wrong user or password" in low or "login failed" in low or "password" in low
                    or " 401" in low or " 403" in low) and "another user" not in low
            if auth:
                self.state["auth_fails"] += 1
                if self.state["auth_fails"] >= MAX_AUTH_FAILS:
                    self.state["suspended"] = True
                    self.e.event("WARN", "router", "Stopped signing in to your router after 3 failed attempts, so "
                                 "it can't lock the account. Check the password in Settings, then press Retry.",
                                 notify=True)
            self.state["error"] = _friendly(msg, cfg)
            self.e.log_error("router poll")
            if manual:
                raise RuntimeError(self.state["error"])
            return self.snap
        finally:
            self.state["running"] = False
            self.lock.release()
        self._after(snap)
        return snap

    # ------------------------------------------------------------------ reading
    def _client(self, cfg):
        _lib()
        from tplinkrouterc6u import TplinkRouterProvider
        clients = TplinkRouterProvider.get_clients()
        name = self.state.get("client")
        if name and name in clients:
            r = clients[name](cfg["host"], cfg["password"], cfg["user"], None, False, 15)
            r.authorize()
            return r
        # Try the ISP (EX) family first - that's what brsk, Sky and others supply - then everything else.
        # Each attempt is one login try, so stop at the first that works.
        order = [n for n in EX_CLIENTS if n in clients] + [n for n in clients if n not in EX_CLIENTS]
        last = None
        for n in order[:6]:
            r = clients[n](cfg["host"], cfg["password"], cfg["user"], None, False, 15)
            try:
                r.authorize()
            except Exception as ex:
                last = ex
                if "password" in str(ex).lower() or "wrong user" in str(ex).lower():
                    raise  # protocol matched but credentials wrong - don't keep trying other clients
                continue
            self.state["client"] = n
            return r
        raise RuntimeError(f"Couldn't sign in to the router with any supported method ({last})")

    def _read(self, cfg):
        r = self._client(cfg)
        out = {"ts": time.time(), "client": self.state["client"], "host": cfg["host"], "raw": {}}
        try:
            try:
                fw = r.get_firmware()
                out.update(model=fw.model, hardware=fw.hardware_version, firmware=fw.firmware_version)
            except Exception:
                pass
            st = r.get_status()
            out["wan"] = {"ip": _s(st.wan_ipv4_addr), "gateway": _s(st.wan_ipv4_gateway), "mac": _s(st.wan_macaddr),
                          "uptime_s": getattr(st, "wan_ipv4_uptime", None)}
            out["lan"] = {"ip": _s(st.lan_ipv4_addr), "mac": _s(st.lan_macaddr)}
            out["cpu_pct"] = round(st.cpu_usage * 100, 1) if st.cpu_usage is not None else None
            out["mem_pct"] = round(st.mem_usage * 100, 1) if st.mem_usage is not None else None
            out["wifi"] = []
            for band, key in (("2.4 GHz", "2g"), ("5 GHz", "5g"), ("6 GHz", "6g")):
                main = getattr(st, f"wifi_{key}_enable", None)
                if main is None and band == "6 GHz":
                    continue
                out["wifi"].append({"band": band, "main": main, "guest": getattr(st, f"guest_{key}_enable", None),
                                    "iot": getattr(st, f"iot_{key}_enable", None)})
            clients = []
            for d in st.devices or []:
                kind, band = _conn_info(d.type)
                clients.append({"mac": norm_mac(d.macaddr), "ip": _s(d.ipaddr), "hostname": d.hostname or "",
                                "kind": kind, "band": band, "signal": d.signal, "ssid": d.ssid,
                                "down_bps": d.down_speed, "up_bps": d.up_speed})
            out["clients"] = clients
            out["counts"] = {"wired": st.wired_total, "wifi": st.wifi_clients_total,
                             "guest": st.guest_clients_total, "iot": st.iot_clients_total or 0,
                             "total": st.clients_total}
            try:
                v4 = r.get_ipv4_status()
                out["wan"].update(conn_type=getattr(v4, "wan_ipv4_conntype", None),
                                  dns=[x for x in (_s(getattr(v4, "wan_ipv4_pridns", None)),
                                                   _s(getattr(v4, "wan_ipv4_snddns", None))) if x and x != "0.0.0.0"])
                out["lan"].update(netmask=_s(getattr(v4, "lan_ipv4_netmask", None)),
                                  dhcp=getattr(v4, "lan_ipv4_dhcp_enable", None))
            except Exception:
                pass
            try:
                leases = {norm_mac(x.macaddr): x.lease_time for x in r.get_ipv4_dhcp_leases()}
                for c in clients:
                    c["lease"] = leases.get(c["mac"])
            except Exception:
                pass
            if hasattr(r, "req_act") and hasattr(r, "ActItem"):
                self._read_raw(r, out)
        finally:
            try:
                r.logout()
            except Exception:
                pass
        return out

    def _raw(self, r, oid, op="gl"):
        try:
            _, vals = r.req_act([r.ActItem(op, oid)])
            return vals[0] if vals else None
        except Exception:
            return None

    def _read_raw(self, r, out):
        """Extra EX-family detail (SSIDs, channels, WAN link, Ethernet ports) - best effort."""
        wifi_raw = _as_list(self._raw(r, "DEV2_ADT_WIFI_COMMON"))
        wan_raw = _as_list(self._raw(r, "DEV2_ADT_WAN"))
        out["raw"]["wifi"] = _scrub(wifi_raw)
        out["raw"]["wan"] = _scrub(wan_raw)
        for i, row in enumerate(wifi_raw):
            if i < len(out["wifi"]) and isinstance(row, dict):
                w = out["wifi"][i]
                w["ssid"] = _pick(row, "primaryssid", "ssid", exclude=("guest", "iot", "enable", "hide", "bcast", "broadcast"))
                w["guest_ssid"] = _pick(row, "guestssid")
                w["channel"] = _pick(row, "currentchannel", "channel", exclude=("auto", "width", "list", "bandwidth"))
                w["auto_channel"] = _pick(row, "autochannel")
                w["width"] = _pick(row, "bandwidth", "channelwidth", "htmode")
                w["standard"] = _pick(row, "standard", "mode", exclude=("security", "encrypt", "auth"))
                w["tx_power"] = _pick(row, "txpower", "power")
        for row in wan_raw:
            if isinstance(row, dict) and str(row.get("enable", "1")) == "1":
                status = _pick(row, "connstatus", "status", exclude=("enable",))
                if status is not None:
                    s = str(status).lower()
                    out["wan"]["link_status"] = status
                    out["wan"]["up"] = s in ("connected", "up", "1")
                up = _pick(row, "uptime")
                if up and str(up).isdigit() and not out["wan"].get("uptime_s"):
                    out["wan"]["uptime_s"] = int(up)
                break
        oids = [self._port_oid] if self._port_oid else ([] if self._port_tried else list(PORT_OIDS))
        for oid in oids:
            rows = _as_list(self._raw(r, oid))
            if rows and any(isinstance(x, dict) and x for x in rows):
                self._port_oid = oid
                out["raw"]["ports"] = _scrub(rows)
                out["ports"] = parse_ports(rows)
                break
        self._port_tried = True
        dev = self._raw(r, "DEV2_DEV_INFO", "go")
        if isinstance(dev, dict):
            out["raw"]["device"] = _scrub(dev)
            up = _pick(dev, "uptime")
            if up and str(up).isdigit():
                out["uptime_s"] = int(up)

    # ------------------------------------------------------------------ after a successful read
    def _after(self, snap):
        prev = self.snap
        first = not self.state.get("last_ok")
        self.snap = snap
        self.state.update(last_ok=snap["ts"], error=None, auth_fails=0, suspended=False)
        c = snap.get("counts") or {}
        self.history.append({"ts": round(snap["ts"]), "wired": c.get("wired"), "wifi": c.get("wifi"),
                             "guest": c.get("guest"), "iot": c.get("iot"), "cpu": snap.get("cpu_pct"),
                             "mem": snap.get("mem_pct")})
        if first:
            name = " ".join(x for x in (snap.get("model"), snap.get("hardware")) if x) or "your router"
            self.e.event("OK", "router", f"Connected to {name}" + (f" (firmware {snap['firmware']})" if snap.get("firmware") else ""))
        if prev:
            pw, nw = (prev.get("wan") or {}), (snap.get("wan") or {})
            if pw.get("ip") and nw.get("ip") and pw["ip"] != nw["ip"]:
                self.e.event("WARN", "router", f"Your broadband IP address changed from {pw['ip']} to {nw['ip']}")
            pu = prev.get("uptime_s") or pw.get("uptime_s")
            nu = snap.get("uptime_s") or nw.get("uptime_s")
            if pu and nu and nu + 120 < pu and snap["ts"] - prev.get("ts", 0) < 3 * 3600:
                what = "Router restarted" if snap.get("uptime_s") else "Broadband connection reconnected"
                self.e.event("WARN", "router", f"{what} - uptime reset from {_dur(pu)} to {_dur(nu)}", notify=True)
            if pw.get("up") is not False and nw.get("up") is False:
                self.e.event("ALERT", "router", "Your router reports its broadband link is down - this is on the "
                             "provider's side, not your Wi-Fi", notify=True)
            elif pw.get("up") is False and nw.get("up"):
                self.e.event("OK", "router", "Your router's broadband link is back up")
        for note in port_findings(snap.get("ports")):
            if note not in self._noted:
                self._noted.add(note)
                self.e.event("INFO", "router", note)
        self._enrich_devices(snap)
        self._save()

    def _enrich_devices(self, snap):
        """Gives NetWatch's device list the router's names and connection type (wired / which band)."""
        e = self.e
        with e.lock:
            for c in snap.get("clients") or []:
                d = e.devices.get(c["mac"])
                if not d:
                    continue
                changed = False
                if c.get("hostname") and not d.get("hostname"):
                    d["hostname"] = c["hostname"]
                    changed = True
                conn = "Wired" if c["kind"] == "wired" else " ".join(x for x in (
                    "Guest" if c["kind"] == "guest" else None, c.get("band") or "Wi-Fi") if x)
                if d.get("router_conn") != conn:
                    d["router_conn"] = conn
                    changed = True
                if changed:
                    e.store.save_device(c["mac"], d)

    # ------------------------------------------------------------------ views
    def view(self, history=True):
        cfg = self._cfg()
        st = dict(self.state)
        st["next"] = (st["last_try"] + cfg["interval"]) if cfg["enabled"] else None
        out = {"state": st, "configured": bool(cfg["password"]) or bool(self.snap), "enabled": cfg["enabled"],
               "host": cfg["host"],
               "interval": cfg["interval"], "snap": self.snap}
        if self.snap:
            known = {d.get("mac", "").upper(): d for d in self.e.device_list() if d.get("mac")}
            clients = []
            for c in self.snap.get("clients") or []:
                d = known.get(c["mac"])
                clients.append({**c, "netwatch_name": (d.get("name") or d.get("hostname")) if d else None,
                                "key": d["key"] if d else None, "type": d["display_type"] if d else None,
                                "trusted": bool(d.get("trusted")) if d else None,
                                "seen_by_scan": d is not None})
            out["clients"] = clients
            out["findings"] = port_findings(self.snap.get("ports"))
        if history:
            out["history"] = list(self.history)[-2016:]
        return out

    def ai_context(self):
        """Compact router data for the assistant (no secrets, no history series)."""
        v = self.view(history=False)
        snap = dict(v.get("snap") or {})
        if not snap:
            return {"configured": v["configured"], "error": v["state"].get("error")}
        raw = snap.pop("raw", {})
        snap.pop("clients", None)
        h = list(self.history)[-288:]

        def rng(k):
            vals = [p[k] for p in h if p.get(k) is not None]
            return {"min": min(vals), "max": max(vals), "avg": round(sum(vals) / len(vals), 1)} if vals else None
        return {"configured": True, "read_at": time.strftime("%Y-%m-%d %H:%M", time.localtime(snap.get("ts", 0))),
                "router": snap, "clients": v.get("clients"), "port_findings": v.get("findings"),
                "last_24h": {k: rng(k) for k in ("wired", "wifi", "guest", "cpu", "mem")},
                "raw_router_fields": raw, "last_error": v["state"].get("error")}


def _s(v):
    return str(v) if v is not None else None


def _dur(s):
    s = int(s or 0)
    d, rem = divmod(s, 86400)
    h, rem = divmod(rem, 3600)
    return f"{d}d {h}h" if d else f"{h}h {rem // 60}m"


def _friendly(msg, cfg):
    m = msg.lower()
    if "wrong user or password" in m or "password" in m:
        return (f"The router rejected the sign-in. Check the admin password (it's the one you use at "
                f"{cfg['host']}). Some ISP routers want the username 'user' instead of 'admin'.")
    if "timed out" in m or "timeout" in m or ("connection" in m and "refused" in m):
        return f"Couldn't reach the router at {cfg['host']}."
    if "another user" in m or ("logged" in m and "already" in m):
        return "Someone is signed in to the router's web page - it allows one admin at a time. NetWatch will try again later."
    return msg[:300]
