"""
Thin wrappers over native Windows APIs (via ctypes) with non-Windows fallbacks
so the rest of the app can be developed and tested anywhere.

  * ICMP ping and traceroute        (iphlpapi IcmpSendEcho)
  * System DNS servers              (iphlpapi GetNetworkParams)
  * Per-app TCP bandwidth           (iphlpapi Get/SetPerTcpConnectionEStats - admin only)
  * Secret storage                  (crypt32 DPAPI)
  * Admin check / relaunch elevated (shell32)
  * Start with Windows              (HKCU Run key)
  * Single instance                 (named mutex)
"""

import base64
import ctypes
import os
import re
import socket
import struct
import subprocess
import sys
import time

IS_WINDOWS = os.name == "nt"
NO_WINDOW = 0x08000000 if IS_WINDOWS else 0


def run_cmd(args, timeout=20):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                           creationflags=NO_WINDOW, errors="replace")
        return r.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def ip_to_dword(ip):
    """IPv4 string -> DWORD in network byte order as Windows expects in memory."""
    return int.from_bytes(socket.inet_aton(ip), "little")


def dword_to_ip(value):
    return socket.inet_ntoa(struct.pack("<L", value & 0xFFFFFFFF))


# --------------------------------------------------------------------------- #
# ICMP
# --------------------------------------------------------------------------- #

IP_SUCCESS = 0
IP_TTL_EXPIRED_TRANSIT = 11013

if IS_WINDOWS:
    from ctypes import wintypes

    class IP_OPTION_INFORMATION(ctypes.Structure):
        _fields_ = [("Ttl", ctypes.c_ubyte), ("Tos", ctypes.c_ubyte),
                    ("Flags", ctypes.c_ubyte), ("OptionsSize", ctypes.c_ubyte),
                    ("OptionsData", ctypes.c_void_p)]

    class ICMP_ECHO_REPLY(ctypes.Structure):
        _fields_ = [("Address", ctypes.c_ulong), ("Status", ctypes.c_ulong),
                    ("RoundTripTime", ctypes.c_ulong), ("DataSize", ctypes.c_ushort),
                    ("Reserved", ctypes.c_ushort), ("Data", ctypes.c_void_p),
                    ("Options", IP_OPTION_INFORMATION)]

    _iphlp = ctypes.WinDLL("iphlpapi.dll")
    _iphlp.IcmpCreateFile.restype = ctypes.c_void_p
    _iphlp.IcmpCloseHandle.argtypes = [ctypes.c_void_p]
    _iphlp.IcmpSendEcho.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_char_p, ctypes.c_ushort,
                                    ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong]
    _iphlp.IcmpSendEcho.restype = ctypes.c_ulong
    _INVALID_HANDLE = ctypes.c_void_p(-1).value


def icmp_echo(ip, timeout_ms=1000, ttl=128):
    """Returns (status, rtt_ms, responder_ip) or None if no reply at all."""
    if not IS_WINDOWS:
        return _fallback_echo(ip, timeout_ms, ttl)
    handle = _iphlp.IcmpCreateFile()
    if not handle or handle == _INVALID_HANDLE:
        return None
    try:
        payload = b"NetWatch-probe-0123456789abcdef"
        size = ctypes.sizeof(ICMP_ECHO_REPLY) + len(payload) + 8
        buf = ctypes.create_string_buffer(size)
        opts = IP_OPTION_INFORMATION(Ttl=ttl)
        n = _iphlp.IcmpSendEcho(handle, ip_to_dword(ip), payload, len(payload),
                                ctypes.byref(opts), buf, size, timeout_ms)
        if n == 0:
            return None
        reply = ICMP_ECHO_REPLY.from_buffer(buf)
        return reply.Status, float(reply.RoundTripTime), dword_to_ip(reply.Address)
    finally:
        _iphlp.IcmpCloseHandle(handle)


def _fallback_echo(ip, timeout_ms, ttl):
    start = time.perf_counter()
    try:
        out = subprocess.run(["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), "-t", str(ttl), ip],
                             capture_output=True, text=True, timeout=timeout_ms / 1000 + 2)
    except (OSError, subprocess.SubprocessError):
        return None
    text = out.stdout
    if out.returncode == 0:
        m = re.search(r"time[=<]([\d.]+)", text)
        return IP_SUCCESS, float(m.group(1)) if m else (time.perf_counter() - start) * 1000, ip
    m = re.search(r"From (\d+\.\d+\.\d+\.\d+).*(?:Time to live exceeded|ttl)", text, re.I)
    if m:
        return IP_TTL_EXPIRED_TRANSIT, (time.perf_counter() - start) * 1000, m.group(1)
    return None


def ping(ip, timeout_ms=1000):
    """Round-trip time in ms, or None."""
    try:
        r = icmp_echo(ip, timeout_ms)
    except Exception:
        return None
    return r[1] if r and r[0] == IP_SUCCESS else None


# --------------------------------------------------------------------------- #
# System DNS servers
# --------------------------------------------------------------------------- #

if IS_WINDOWS:
    class IP_ADDR_STRING(ctypes.Structure):
        pass
    IP_ADDR_STRING._fields_ = [("Next", ctypes.POINTER(IP_ADDR_STRING)),
                               ("IpAddress", ctypes.c_char * 16),
                               ("IpMask", ctypes.c_char * 16),
                               ("Context", ctypes.c_ulong)]

    class FIXED_INFO(ctypes.Structure):
        _fields_ = [("HostName", ctypes.c_char * 132), ("DomainName", ctypes.c_char * 132),
                    ("CurrentDnsServer", ctypes.POINTER(IP_ADDR_STRING)),
                    ("DnsServerList", IP_ADDR_STRING),
                    ("NodeType", ctypes.c_uint), ("ScopeId", ctypes.c_char * 260),
                    ("EnableRouting", ctypes.c_uint), ("EnableProxy", ctypes.c_uint),
                    ("EnableDns", ctypes.c_uint)]


def system_dns_servers():
    servers = []
    try:
        if IS_WINDOWS:
            size = ctypes.c_ulong(0)
            _iphlp.GetNetworkParams(None, ctypes.byref(size))
            buf = ctypes.create_string_buffer(size.value)
            if _iphlp.GetNetworkParams(buf, ctypes.byref(size)) == 0:
                info = FIXED_INFO.from_buffer(buf)
                node = info.DnsServerList
                while True:
                    ip = node.IpAddress.decode(errors="ignore").strip("\x00 ")
                    if ip and ip != "0.0.0.0":
                        servers.append(ip)
                    if not node.Next:
                        break
                    node = node.Next.contents
        else:
            with open("/etc/resolv.conf") as fh:
                for line in fh:
                    if line.startswith("nameserver"):
                        servers.append(line.split()[1])
    except Exception:
        pass
    v4 = []
    for s in servers:
        try:
            socket.inet_aton(s)
            if s not in v4:
                v4.append(s)
        except OSError:
            pass
    return v4


# --------------------------------------------------------------------------- #
# Admin, elevation, startup, single instance
# --------------------------------------------------------------------------- #

def is_admin():
    if IS_WINDOWS:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False
    return hasattr(os, "geteuid") and os.geteuid() == 0


def launch_command():
    """(executable, arguments) that start this app."""
    if getattr(sys, "frozen", False):
        return sys.executable, ""
    exe = sys.executable
    if IS_WINDOWS and exe.lower().endswith("python.exe"):
        exe = exe[:-10] + "pythonw.exe"
    script = os.path.abspath(sys.argv[0])
    return exe, f'"{script}"'


def relaunch_as_admin(extra_args=""):
    if not IS_WINDOWS:
        return False
    exe, args = launch_command()
    rc = ctypes.windll.shell32.ShellExecuteW(None, "runas", exe, f"{args} {extra_args}".strip(), None, 1)
    return rc > 32


RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_RUN_NAME = "NetWatch"


def get_start_with_windows():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, APP_RUN_NAME)
            return True
    except (OSError, ImportError):
        return False


def set_start_with_windows(enabled):
    try:
        import winreg
    except ImportError:
        return False
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if enabled:
            exe, args = launch_command()
            winreg.SetValueEx(k, APP_RUN_NAME, 0, winreg.REG_SZ, f'"{exe}" {args} --minimized'.replace("  ", " "))
        else:
            try:
                winreg.DeleteValue(k, APP_RUN_NAME)
            except OSError:
                pass
    return True


_mutex = None


def acquire_single_instance(name="Global\\NetWatchSingleInstance"):
    """True if this is the only running instance."""
    global _mutex
    if not IS_WINDOWS:
        return True
    k32 = ctypes.windll.kernel32
    k32.CreateMutexW.restype = ctypes.c_void_p
    _mutex = k32.CreateMutexW(None, False, name)
    return k32.GetLastError() != 183  # ERROR_ALREADY_EXISTS


def release_single_instance():
    global _mutex
    if IS_WINDOWS and _mutex:
        ctypes.windll.kernel32.CloseHandle(ctypes.c_void_p(_mutex))
        _mutex = None


# --------------------------------------------------------------------------- #
# DPAPI secret protection (passwords are encrypted to the current Windows user)
# --------------------------------------------------------------------------- #

if IS_WINDOWS:
    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]


def protect(secret):
    if not secret:
        return ""
    data = secret.encode("utf-8")
    if IS_WINDOWS:
        try:
            blob_in = DATA_BLOB(len(data), ctypes.cast(ctypes.create_string_buffer(data, len(data)),
                                                       ctypes.POINTER(ctypes.c_char)))
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptProtectData(ctypes.byref(blob_in), "NetWatch", None, None,
                                                      None, 0, ctypes.byref(blob_out)):
                enc = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return "dpapi:" + base64.b64encode(enc).decode()
        except Exception:
            pass
    return "b64:" + base64.b64encode(data).decode()


def unprotect(value):
    if not value:
        return ""
    try:
        if value.startswith("dpapi:") and IS_WINDOWS:
            raw = base64.b64decode(value[6:])
            blob_in = DATA_BLOB(len(raw), ctypes.cast(ctypes.create_string_buffer(raw, len(raw)),
                                                      ctypes.POINTER(ctypes.c_char)))
            blob_out = DATA_BLOB()
            if ctypes.windll.crypt32.CryptUnprotectData(ctypes.byref(blob_in), None, None, None,
                                                        None, 0, ctypes.byref(blob_out)):
                dec = ctypes.string_at(blob_out.pbData, blob_out.cbData)
                ctypes.windll.kernel32.LocalFree(blob_out.pbData)
                return dec.decode("utf-8")
            return ""
        if value.startswith("b64:"):
            return base64.b64decode(value[4:]).decode("utf-8")
    except Exception:
        return ""
    return value


# --------------------------------------------------------------------------- #
# Per-application TCP bandwidth (TCP extended statistics, requires admin)
# --------------------------------------------------------------------------- #

TCP_TABLE_OWNER_PID_ALL = 5
MIB_TCP_STATE_ESTAB = 5
TcpConnectionEstatsData = 1

if IS_WINDOWS:
    class MIB_TCPROW(ctypes.Structure):
        _fields_ = [("dwState", wintypes.DWORD), ("dwLocalAddr", wintypes.DWORD),
                    ("dwLocalPort", wintypes.DWORD), ("dwRemoteAddr", wintypes.DWORD),
                    ("dwRemotePort", wintypes.DWORD)]

    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [("dwState", wintypes.DWORD), ("dwLocalAddr", wintypes.DWORD),
                    ("dwLocalPort", wintypes.DWORD), ("dwRemoteAddr", wintypes.DWORD),
                    ("dwRemotePort", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD)]

    class MIB_TCP6ROW(ctypes.Structure):
        _fields_ = [("State", wintypes.DWORD), ("LocalAddr", ctypes.c_ubyte * 16),
                    ("dwLocalScopeId", wintypes.DWORD), ("dwLocalPort", wintypes.DWORD),
                    ("RemoteAddr", ctypes.c_ubyte * 16), ("dwRemoteScopeId", wintypes.DWORD),
                    ("dwRemotePort", wintypes.DWORD)]

    class MIB_TCP6ROW_OWNER_PID(ctypes.Structure):
        _fields_ = [("ucLocalAddr", ctypes.c_ubyte * 16), ("dwLocalScopeId", wintypes.DWORD),
                    ("dwLocalPort", wintypes.DWORD), ("ucRemoteAddr", ctypes.c_ubyte * 16),
                    ("dwRemoteScopeId", wintypes.DWORD), ("dwRemotePort", wintypes.DWORD),
                    ("dwState", wintypes.DWORD), ("dwOwningPid", wintypes.DWORD)]

    class TCP_ESTATS_DATA_RW_v0(ctypes.Structure):
        _fields_ = [("EnableCollection", ctypes.c_ubyte)]

    class TCP_ESTATS_DATA_ROD_v0(ctypes.Structure):
        _fields_ = [("DataBytesOut", ctypes.c_uint64), ("DataSegsOut", ctypes.c_uint64),
                    ("DataBytesIn", ctypes.c_uint64), ("DataSegsIn", ctypes.c_uint64),
                    ("SegsOut", ctypes.c_uint64), ("SegsIn", ctypes.c_uint64),
                    ("SoftErrors", ctypes.c_ulong), ("SoftErrorReason", ctypes.c_ulong),
                    ("SndUna", ctypes.c_ulong), ("SndNxt", ctypes.c_ulong), ("SndMax", ctypes.c_ulong),
                    ("ThruBytesAcked", ctypes.c_uint64), ("RcvNxt", ctypes.c_ulong),
                    ("ThruBytesReceived", ctypes.c_uint64)]


def _tcp_table(family):
    size = wintypes.DWORD(0)
    _iphlp.GetExtendedTcpTable(None, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0)
    for _ in range(3):
        buf = ctypes.create_string_buffer(size.value + 4096)
        size = wintypes.DWORD(len(buf))
        if _iphlp.GetExtendedTcpTable(buf, ctypes.byref(size), False, family, TCP_TABLE_OWNER_PID_ALL, 0) == 0:
            count = ctypes.c_ulong.from_buffer(buf).value
            row_t = MIB_TCPROW_OWNER_PID if family == socket.AF_INET else MIB_TCP6ROW_OWNER_PID
            offset = ctypes.sizeof(ctypes.c_ulong)
            return (row_t * count).from_buffer(buf, offset)
    return []


class TcpBandwidthTracker:
    """Samples cumulative bytes per established TCP connection and sums deltas per PID."""

    def __init__(self):
        self.available = IS_WINDOWS and is_admin()
        self._last = {}  # conn key -> (bytes_in, bytes_out)

    def _rows(self):
        for r in _tcp_table(socket.AF_INET):
            if r.dwState != MIB_TCP_STATE_ESTAB:
                continue
            row = MIB_TCPROW(r.dwState, r.dwLocalAddr, r.dwLocalPort, r.dwRemoteAddr, r.dwRemotePort)
            key = (4, r.dwLocalAddr, r.dwLocalPort, r.dwRemoteAddr, r.dwRemotePort)
            yield key, r.dwOwningPid, row, False
        for r in _tcp_table(socket.AF_INET6):
            if r.dwState != MIB_TCP_STATE_ESTAB:
                continue
            row = MIB_TCP6ROW()
            row.State = r.dwState
            row.LocalAddr = r.ucLocalAddr
            row.dwLocalScopeId = r.dwLocalScopeId
            row.dwLocalPort = r.dwLocalPort
            row.RemoteAddr = r.ucRemoteAddr
            row.dwRemoteScopeId = r.dwRemoteScopeId
            row.dwRemotePort = r.dwRemotePort
            key = (6, bytes(r.ucLocalAddr), r.dwLocalPort, bytes(r.ucRemoteAddr), r.dwRemotePort)
            yield key, r.dwOwningPid, row, True

    def sample(self):
        """Returns {pid: (bytes_in_delta, bytes_out_delta)} since the last call."""
        if not self.available:
            return {}
        per_pid = {}
        seen = {}
        rw = TCP_ESTATS_DATA_RW_v0(1)
        rod = TCP_ESTATS_DATA_ROD_v0()
        for key, pid, row, v6 in self._rows():
            getter = _iphlp.GetPerTcp6ConnectionEStats if v6 else _iphlp.GetPerTcpConnectionEStats
            setter = _iphlp.SetPerTcp6ConnectionEStats if v6 else _iphlp.SetPerTcpConnectionEStats
            if key not in self._last:
                setter(ctypes.byref(row), TcpConnectionEstatsData, ctypes.byref(rw), 0, ctypes.sizeof(rw), 0)
            res = getter(ctypes.byref(row), TcpConnectionEstatsData, None, 0, 0, None, 0, 0,
                         ctypes.byref(rod), 0, ctypes.sizeof(rod))
            if res != 0:
                continue
            cur = (rod.DataBytesIn, rod.DataBytesOut)
            prev = self._last.get(key)
            seen[key] = cur
            if prev:
                din, dout = max(0, cur[0] - prev[0]), max(0, cur[1] - prev[1])
                a, b = per_pid.get(pid, (0, 0))
                per_pid[pid] = (a + din, b + dout)
        self._last = seen
        return per_pid
