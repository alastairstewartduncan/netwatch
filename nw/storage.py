"""SQLite storage for history, events, speed tests, service checks and devices."""

import json
import sqlite3
import threading
import time
from datetime import datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS minute_stats (
    ts INTEGER PRIMARY KEY, online REAL, latency REAL, latency_max REAL, jitter REAL,
    loss REAL, gw_latency REAL, down REAL, up REAL, wifi_signal REAL, dns_ms REAL);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, level TEXT, category TEXT, message TEXT);
CREATE INDEX IF NOT EXISTS ix_events_ts ON events(ts);
CREATE TABLE IF NOT EXISTS outages (
    id INTEGER PRIMARY KEY AUTOINCREMENT, start INTEGER, end INTEGER, cause TEXT);
CREATE TABLE IF NOT EXISTS speedtests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts INTEGER, down REAL, up REAL, ping REAL,
    jitter REAL, server TEXT, isp TEXT, trigger TEXT);
CREATE TABLE IF NOT EXISTS service_results (
    ts INTEGER, check_id TEXT, ok INTEGER, ms REAL, detail TEXT);
CREATE INDEX IF NOT EXISTS ix_service ON service_results(check_id, ts);
CREATE TABLE IF NOT EXISTS dns_stats (ts INTEGER, server TEXT, ms REAL, ok REAL);
CREATE INDEX IF NOT EXISTS ix_dns ON dns_stats(ts);
CREATE TABLE IF NOT EXISTS app_usage (day TEXT, process TEXT, bytes_in REAL, bytes_out REAL,
    PRIMARY KEY(day, process));
CREATE TABLE IF NOT EXISTS devices (
    key TEXT PRIMARY KEY, data TEXT);
CREATE TABLE IF NOT EXISTS device_presence (ts INTEGER, key TEXT);
CREATE INDEX IF NOT EXISTS ix_presence ON device_presence(ts);
CREATE TABLE IF NOT EXISTS wifi_roams (ts INTEGER, ssid TEXT, from_bssid TEXT, to_bssid TEXT, channel INTEGER, signal REAL);
CREATE TABLE IF NOT EXISTS wifi_aps (bssid TEXT PRIMARY KEY, ssid TEXT, channel INTEGER, band TEXT,
    first_seen INTEGER, last_seen INTEGER, samples INTEGER, signal_sum REAL);
CREATE TABLE IF NOT EXISTS known_apps (path TEXT PRIMARY KEY, name TEXT, first_seen INTEGER, signed TEXT,
    publisher TEXT, blocked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS failovers (id INTEGER PRIMARY KEY AUTOINCREMENT, start INTEGER, end INTEGER, isp TEXT);
CREATE TABLE IF NOT EXISTS geo_cache (ip TEXT PRIMARY KEY, data TEXT, ts INTEGER);
CREATE TABLE IF NOT EXISTS sites (name TEXT PRIMARY KEY, last_seen INTEGER, data TEXT);
"""


class Store:
    def __init__(self, path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False, isolation_level=None)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.lock = threading.RLock()
        with self.lock:
            self.db.executescript(SCHEMA)
            cols = {r[1] for r in self.db.execute("PRAGMA table_info(speedtests)")}
            for col, typ in (("idle_ms", "REAL"), ("down_loaded_ms", "REAL"), ("up_loaded_ms", "REAL"), ("grade", "TEXT")):
                if col not in cols:
                    self.db.execute(f"ALTER TABLE speedtests ADD COLUMN {col} {typ}")

    def _q(self, sql, args=()):
        with self.lock:
            return self.db.execute(sql, args).fetchall()

    def _x(self, sql, args=()):
        with self.lock:
            cur = self.db.execute(sql, args)
            return cur.lastrowid

    # ---------------------------------------------------------------- writes
    def add_minute(self, row):
        self._x("INSERT OR REPLACE INTO minute_stats VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (row["ts"], row.get("online"), row.get("latency"), row.get("latency_max"),
                 row.get("jitter"), row.get("loss"), row.get("gw_latency"), row.get("down"),
                 row.get("up"), row.get("wifi_signal"), row.get("dns_ms")))

    def add_event(self, ts, level, category, message):
        return self._x("INSERT INTO events(ts, level, category, message) VALUES (?,?,?,?)",
                       (int(ts), level, category, message))

    def start_outage(self, ts, cause):
        return self._x("INSERT INTO outages(start, end, cause) VALUES (?,?,?)", (int(ts), None, cause))

    def end_outage(self, oid, ts):
        self._x("UPDATE outages SET end=? WHERE id=?", (int(ts), oid))

    def close_open_outages(self):
        # Outages still open from a previous run end at the last recorded minute
        last = self._q("SELECT MAX(ts) FROM minute_stats")[0][0]
        self._x("UPDATE outages SET end=COALESCE(?, start) WHERE end IS NULL", (last,))

    def add_speedtest(self, r, trigger):
        self._x("INSERT INTO speedtests(ts, down, up, ping, jitter, server, isp, trigger, idle_ms, down_loaded_ms, "
                "up_loaded_ms, grade) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                (int(r["ts"]), r["down"], r["up"], r["ping"], r["jitter"], r.get("server", ""),
                 r.get("isp", ""), trigger, r.get("idle_ms"), r.get("down_loaded_ms"), r.get("up_loaded_ms"),
                 r.get("grade")))

    def add_service_result(self, ts, check_id, ok, ms, detail):
        self._x("INSERT INTO service_results VALUES (?,?,?,?,?)", (int(ts), check_id, int(ok), ms, detail))

    def add_dns_stat(self, ts, server, ms, ok):
        self._x("INSERT INTO dns_stats VALUES (?,?,?,?)", (int(ts), server, ms, ok))

    def add_app_usage(self, day, process, bin_, bout):
        self._x("""INSERT INTO app_usage VALUES (?,?,?,?) ON CONFLICT(day, process) DO UPDATE SET
                   bytes_in = bytes_in + excluded.bytes_in, bytes_out = bytes_out + excluded.bytes_out""",
                (day, process, bin_, bout))

    def purge(self, retention_days):
        cutoff = int(time.time() - retention_days * 86400)
        with self.lock:
            for table, col in (("minute_stats", "ts"), ("events", "ts"), ("service_results", "ts"),
                               ("dns_stats", "ts"), ("outages", "start"), ("speedtests", "ts"),
                               ("device_presence", "ts"), ("wifi_roams", "ts"), ("failovers", "start")):
                self.db.execute(f"DELETE FROM {table} WHERE {col} < ?", (cutoff,))
            day = (datetime.now() - timedelta(days=retention_days)).strftime("%Y-%m-%d")
            self.db.execute("DELETE FROM app_usage WHERE day < ?", (day,))

    # ---------------------------------------------------------------- devices
    def load_devices(self):
        return {k: json.loads(v) for k, v in self._q("SELECT key, data FROM devices")}

    def save_device(self, key, data):
        self._x("INSERT OR REPLACE INTO devices VALUES (?,?)", (key, json.dumps(data)))

    def delete_device(self, key):
        self._x("DELETE FROM devices WHERE key=?", (key,))

    # ---------------------------------------------------------------- reads
    def events(self, limit=500, since_id=0):
        rows = self._q("SELECT id, ts, level, category, message FROM events WHERE id > ? "
                       "ORDER BY id DESC LIMIT ?", (since_id, limit))
        return [dict(zip(("id", "ts", "level", "category", "message"), r)) for r in rows]

    def speedtests(self, since=0, limit=200):
        rows = self._q("SELECT ts, down, up, ping, jitter, server, isp, trigger, idle_ms, down_loaded_ms, up_loaded_ms, "
                       "grade FROM speedtests WHERE ts >= ? ORDER BY ts DESC LIMIT ?", (since, limit))
        return [dict(zip(("ts", "down", "up", "ping", "jitter", "server", "isp", "trigger", "idle_ms",
                          "down_loaded_ms", "up_loaded_ms", "grade"), r)) for r in rows]

    def service_history(self, check_id, since):
        rows = self._q("SELECT ts, ok, ms FROM service_results WHERE check_id=? AND ts>=? ORDER BY ts",
                       (check_id, since))
        return rows

    def service_uptime(self, check_id, since):
        r = self._q("SELECT AVG(ok), AVG(ms) FROM service_results WHERE check_id=? AND ts>=?", (check_id, since))
        return r[0] if r else (None, None)

    def dns_history(self, since):
        return self._q("SELECT ts, server, ms, ok FROM dns_stats WHERE ts>=? ORDER BY ts", (since,))

    def app_usage(self, day):
        rows = self._q("SELECT process, bytes_in, bytes_out FROM app_usage WHERE day=? "
                       "ORDER BY bytes_in + bytes_out DESC LIMIT 25", (day,))
        return [{"process": p, "bytes_in": i, "bytes_out": o} for p, i, o in rows]

    def history(self, hours):
        now = int(time.time())
        since = now - hours * 3600
        bucket = max(60, (hours * 3600) // 300)  # ~300 points
        bucket -= bucket % 60
        rows = self._q(f"""SELECT (ts / {bucket}) * {bucket} AS b, AVG(online), AVG(latency), MAX(latency_max),
                           AVG(jitter), AVG(loss), AVG(gw_latency), AVG(down), AVG(up), MAX(down),
                           AVG(wifi_signal), AVG(dns_ms), COUNT(*)
                           FROM minute_stats WHERE ts >= ? GROUP BY b ORDER BY b""", (since,))
        keys = ("ts", "online", "latency", "latency_max", "jitter", "loss", "gw_latency", "down", "up",
                "down_peak", "wifi_signal", "dns_ms", "minutes")
        series = [dict(zip(keys, r)) for r in rows]

        summary = self._q("""SELECT AVG(online), AVG(latency), AVG(loss), COUNT(*), AVG(jitter), MAX(down)
                             FROM minute_stats WHERE ts >= ?""", (since,))[0]
        outages = self._q("""SELECT start, COALESCE(end, ?), cause FROM outages
                             WHERE COALESCE(end, ?) >= ? ORDER BY start DESC""", (now, now, since))
        out_list = [{"start": s, "end": e, "duration": max(0, e - s), "cause": c} for s, e, c in outages]

        days = []
        span_days = max(1, hours // 24)
        for i in range(span_days - 1, -1, -1):
            d0 = datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=i)
            t0, t1 = int(d0.timestamp()), int((d0 + timedelta(days=1)).timestamp())
            r = self._q("SELECT AVG(online), COUNT(*), AVG(latency), AVG(loss) FROM minute_stats "
                        "WHERE ts >= ? AND ts < ?", (t0, t1))[0]
            down_s = sum(max(0, min(e, t1) - max(s, t0)) for s, e, _ in outages if s < t1 and e > t0)
            days.append({"date": d0.strftime("%Y-%m-%d"), "uptime": None if r[0] is None else r[0] * 100,
                         "monitored_min": r[1], "latency": r[2], "loss": r[3], "outage_s": down_s})

        speeds = self.speedtests(since)
        return {
            "hours": hours, "bucket": bucket, "series": series,
            "summary": {"uptime": None if summary[0] is None else summary[0] * 100,
                        "latency": summary[1], "loss": summary[2], "monitored_min": summary[3],
                        "jitter": summary[4], "peak_down": summary[5],
                        "outages": len(out_list), "outage_s": sum(o["duration"] for o in out_list),
                        "avg_speed_down": (sum(s["down"] for s in speeds) / len(speeds)) if speeds else None,
                        "avg_speed_up": (sum(s["up"] for s in speeds) / len(speeds)) if speeds else None},
            "outages": out_list[:200], "days": days, "speedtests": speeds,
        }

    def export_minutes(self, hours):
        since = int(time.time()) - hours * 3600
        return self._q("SELECT * FROM minute_stats WHERE ts >= ? ORDER BY ts", (since,))

    # ---------------------------------------------------------------- v3 additions
    def add_presence(self, ts, keys):
        with self.lock:
            self.db.executemany("INSERT INTO device_presence VALUES (?,?)", [(int(ts), k) for k in keys])

    def presence(self, since):
        return self._q("SELECT ts, key FROM device_presence WHERE ts >= ? ORDER BY ts", (since,))

    def add_roam(self, ts, ssid, frm, to, channel, signal):
        self._x("INSERT INTO wifi_roams VALUES (?,?,?,?,?,?)", (int(ts), ssid, frm, to, channel, signal))

    def roams(self, since):
        rows = self._q("SELECT ts, ssid, from_bssid, to_bssid, channel, signal FROM wifi_roams WHERE ts >= ? "
                       "ORDER BY ts DESC LIMIT 200", (since,))
        return [dict(zip(("ts", "ssid", "from", "to", "channel", "signal"), r)) for r in rows]

    def touch_ap(self, bssid, ssid, channel, band, signal, ts):
        self._x("""INSERT INTO wifi_aps VALUES (?,?,?,?,?,?,1,?) ON CONFLICT(bssid) DO UPDATE SET
                   ssid=excluded.ssid, channel=excluded.channel, band=excluded.band, last_seen=excluded.last_seen,
                   samples=samples+1, signal_sum=signal_sum+excluded.signal_sum""",
                (bssid, ssid, channel, band, int(ts), int(ts), signal or 0))

    def aps(self):
        rows = self._q("SELECT bssid, ssid, channel, band, first_seen, last_seen, samples, signal_sum FROM wifi_aps "
                       "ORDER BY last_seen DESC")
        return [{"bssid": b, "ssid": s, "channel": c, "band": bd, "first_seen": f, "last_seen": l,
                 "minutes": round(n * 5 / 60, 1), "avg_signal": ss / n if n else None}
                for b, s, c, bd, f, l, n, ss in rows]

    def known_apps(self):
        rows = self._q("SELECT path, name, first_seen, signed, publisher, blocked FROM known_apps ORDER BY first_seen DESC")
        return [dict(zip(("path", "name", "first_seen", "signed", "publisher", "blocked"), r)) for r in rows]

    def add_known_app(self, path, name, ts):
        self._x("INSERT OR IGNORE INTO known_apps(path, name, first_seen) VALUES (?,?,?)", (path, name, int(ts)))

    def update_app(self, path, **fields):
        for k, v in fields.items():
            if k in ("signed", "publisher", "blocked"):
                self._x(f"UPDATE known_apps SET {k}=? WHERE path=?", (v, path))

    def start_failover(self, ts, isp):
        return self._x("INSERT INTO failovers(start, end, isp) VALUES (?,?,?)", (int(ts), None, isp))

    def end_failover(self, fid, ts):
        self._x("UPDATE failovers SET end=? WHERE id=?", (int(ts), fid))

    def failovers(self, since):
        now = int(time.time())
        rows = self._q("SELECT start, COALESCE(end, ?), isp FROM failovers WHERE COALESCE(end, ?) >= ? ORDER BY start DESC",
                       (now, now, since))
        return [{"start": s, "end": e, "duration": e - s, "isp": i} for s, e, i in rows]

    def geo_get(self, ips):
        if not ips:
            return {}
        out = {}
        cutoff = int(time.time()) - 30 * 86400
        for ip in ips:
            r = self._q("SELECT data FROM geo_cache WHERE ip=? AND ts>=?", (ip, cutoff))
            if r:
                out[ip] = json.loads(r[0][0])
        return out

    def geo_put(self, data):
        now = int(time.time())
        with self.lock:
            self.db.executemany("INSERT OR REPLACE INTO geo_cache VALUES (?,?,?)",
                                [(ip, json.dumps(d), now) for ip, d in data.items()])

    def put_site(self, name, data):
        self._x("INSERT OR REPLACE INTO sites VALUES (?,?,?)", (name, int(time.time()), json.dumps(data)))

    def sites(self):
        return [{"name": n, "last_seen": t, **json.loads(d)} for n, t, d in
                self._q("SELECT name, last_seen, data FROM sites ORDER BY name")]

    def delete_site(self, name):
        self._x("DELETE FROM sites WHERE name=?", (name,))

    def usage_by_day(self, since):
        """Bytes per day reconstructed from per-minute average rates."""
        rows = self._q("""SELECT date(ts, 'unixepoch', 'localtime') AS d, SUM(COALESCE(down,0))*60, SUM(COALESCE(up,0))*60,
                          COUNT(*) FROM minute_stats WHERE ts >= ? GROUP BY d ORDER BY d""", (since,))
        return [{"date": d, "down": dn, "up": up, "minutes": n} for d, dn, up, n in rows]

    def latency_baseline(self, hour, days=28):
        since = int(time.time()) - days * 86400
        rows = self._q("""SELECT latency, loss, dns_ms FROM minute_stats WHERE ts >= ? AND latency IS NOT NULL
                          AND CAST(strftime('%H', ts, 'unixepoch', 'localtime') AS INTEGER) = ?""", (since, hour))
        return rows

    def recent_minutes(self, minutes):
        since = int(time.time()) - minutes * 60
        return self._q("SELECT ts, online, latency, loss, down, up, dns_ms FROM minute_stats WHERE ts >= ? ORDER BY ts",
                       (since,))
