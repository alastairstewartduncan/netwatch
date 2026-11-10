"""Broadband speed test using Cloudflare's public speed test endpoints (no account or API key)."""

import http.client
import json
import statistics
import threading
import time
import urllib.request

HOST = "speed.cloudflare.com"
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) NetWatch/2.0"


def _meta():
    try:
        req = urllib.request.Request(f"https://{HOST}/meta", headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=8) as r:
            return json.loads(r.read().decode())
    except Exception:
        return {}


def _latency(samples=12):
    rtts = []
    for _ in range(samples):
        conn = http.client.HTTPSConnection(HOST, timeout=5)
        try:
            conn.connect()  # exclude TCP/TLS setup from the measurement
            t = time.perf_counter()
            conn.request("GET", "/__down?bytes=0", headers={"User-Agent": UA})
            conn.getresponse().read()
            rtts.append((time.perf_counter() - t) * 1000)
        except Exception:
            pass
        finally:
            conn.close()
    if not rtts:
        return None, None
    rtts.sort()
    core = rtts[: max(3, len(rtts) - 2)]  # drop outliers
    jitter = statistics.mean(abs(a - b) for a, b in zip(core, core[1:])) if len(core) > 1 else 0
    return statistics.median(core), jitter


class _Meter:
    def __init__(self):
        self.bytes = 0
        self.lock = threading.Lock()

    def add(self, n):
        with self.lock:
            self.bytes += n


def _download_worker(meter, deadline, stop):
    while time.monotonic() < deadline and not stop():
        conn = http.client.HTTPSConnection(HOST, timeout=10)
        try:
            conn.request("GET", "/__down?bytes=50000000", headers={"User-Agent": UA})
            resp = conn.getresponse()
            while time.monotonic() < deadline and not stop():
                chunk = resp.read(65536)
                if not chunk:
                    break
                meter.add(len(chunk))
        except Exception:
            time.sleep(0.2)
        finally:
            conn.close()


def _upload_worker(meter, deadline, stop):
    block = b"0" * 65536
    total = 20 * 1024 * 1024
    while time.monotonic() < deadline and not stop():
        conn = http.client.HTTPSConnection(HOST, timeout=10)
        try:
            conn.putrequest("POST", "/__up")
            conn.putheader("User-Agent", UA)
            conn.putheader("Content-Type", "application/octet-stream")
            conn.putheader("Content-Length", str(total))
            conn.endheaders()
            sent = 0
            while sent < total and time.monotonic() < deadline and not stop():
                conn.send(block)
                sent += len(block)
                meter.add(len(block))
            if sent >= total:
                conn.getresponse().read()
        except Exception:
            time.sleep(0.2)
        finally:
            conn.close()


def _measure(worker, seconds, streams, progress, phase, stop):
    meter = _Meter()
    start = time.monotonic()
    deadline = start + seconds
    threads = [threading.Thread(target=worker, args=(meter, deadline, stop), daemon=True) for _ in range(streams)]
    for t in threads:
        t.start()
    samples = []
    last_b, last_t = 0, start
    while time.monotonic() < deadline and not stop():
        time.sleep(0.25)
        now = time.monotonic()
        b = meter.bytes
        mbps = (b - last_b) * 8 / 1e6 / max(1e-3, now - last_t)
        last_b, last_t = b, now
        if now - start > 1.5:  # ignore TCP slow-start ramp
            samples.append(mbps)
        progress(phase, min(1.0, (now - start) / seconds), mbps)
    for t in threads:
        t.join(timeout=3)
    if not samples:
        return 0.0
    samples.sort()
    return statistics.mean(samples[len(samples) // 4:])  # mean of the upper 75%


def run(progress=lambda phase, frac, mbps: None, stop=lambda: False, duration=10, streams=6):
    """Returns dict(down, up, ping, jitter, server, isp, bufferbloat...) in Mbps / ms."""
    from .diag import LatencySampler, bufferbloat_grade
    meta = _meta()
    sampler = LatencySampler().start()  # measures latency idle and under load (bufferbloat)
    try:
        progress("latency", 0, 0)
        ping, jitter = _latency()
        if ping is None:
            raise RuntimeError("Speed test server unreachable")
        time.sleep(max(0, 2.5 - 0))
        sampler.phase = "download"
        progress("download", 0, 0)
        down = _measure(_download_worker, duration, streams, progress, "download", stop)
        sampler.phase = "gap"
        progress("upload", 0, 0)
        sampler.phase = "upload"
        up = _measure(_upload_worker, max(6, duration - 2), max(3, streams // 2), progress, "upload", stop)
    finally:
        sampler.stop()
    idle, ld, lu = sampler.median("idle"), sampler.median("download"), sampler.median("upload")
    worst = max([x for x in (ld, lu) if x is not None], default=None)
    city = meta.get("city", "")
    colo = meta.get("colo", "")
    return {"ts": time.time(), "down": round(down, 1), "up": round(up, 1), "ping": round(ping, 1),
            "jitter": round(jitter or 0, 1), "server": f"Cloudflare {colo}".strip(),
            "isp": meta.get("asOrganization", ""), "city": city,
            "idle_ms": None if idle is None else round(idle, 1),
            "down_loaded_ms": None if ld is None else round(ld, 1),
            "up_loaded_ms": None if lu is None else round(lu, 1),
            "grade": bufferbloat_grade(idle, worst)}
