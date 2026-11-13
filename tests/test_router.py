"""Tests for the router integration (uses a fake TP-Link client, no network)."""
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

try:
    import tplinkrouterc6u  # noqa: F401
    from fake_router import FakeEX
    HAVE_LIB = True
except ImportError:
    HAVE_LIB = False

from nw import router as R  # noqa: E402


class FakeStore:
    def __init__(self):
        self.saved = {}

    def save_device(self, key, d):
        self.saved[key] = dict(d)


class FakeEngine:
    def __init__(self, tmp):
        self.data_dir = Path(tmp)
        self.settings = {"router_enabled": True, "router_host": "192.168.0.1", "router_user": "admin",
                         "router_password": "secret", "router_interval": 300}
        self.net = {"gateway": "192.168.0.1"}
        self.lock = threading.RLock()
        self.devices = {"AA:BB:CC:00:00:01": {"key": "AA:BB:CC:00:00:01", "mac": "AA:BB:CC:00:00:01", "ip": "192.168.0.10",
                                              "name": "This PC"}}
        self.store = FakeStore()
        self.events = deque()

    def event(self, level, cat, msg, notify=False, remote=True):
        self.events.append((level, cat, msg))

    def log_error(self, where):
        pass

    def device_list(self):
        return [{**d, "display_type": "pc", "online": True} for d in self.devices.values()]


class ParsingTests(unittest.TestCase):
    def test_ports_and_findings(self):
        ports = R.parse_ports([{"name": "LAN3", "status": "Up", "currentBitRate": "100", "maxBitRate": "1000"},
                               {"name": "LAN1", "status": "Down"},
                               {"Name": "WAN", "Status": "Up", "CurrentBitRate": "2.5G"}])
        self.assertEqual(ports[0], {"name": "LAN3", "up": True, "speed_mbps": 100, "max_mbps": 1000, "duplex": None})
        self.assertFalse(ports[1]["up"])
        self.assertEqual(ports[2]["speed_mbps"], 2500)
        notes = R.port_findings(ports)
        self.assertEqual(len(notes), 1)
        self.assertIn("LAN3", notes[0])

    def test_scrub_removes_secrets(self):
        out = R._scrub({"SSID": "x", "KeyPassphrase": "p", "nested": [{"wpaPsk": "p", "ok": 1}]})
        self.assertEqual(out, {"SSID": "x", "nested": [{"ok": 1}]})


@unittest.skipUnless(HAVE_LIB, "tplinkrouterc6u not installed")
class RouterLinkTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.e = FakeEngine(self.tmp.name)
        FakeEX.fail_login, FakeEX.logins, FakeEX.logouts = False, 0, 0
        self.link = R.RouterLink(self.e)
        self.link.state["client"] = "FakeEX"
        import tplinkrouterc6u
        self._orig = tplinkrouterc6u.TplinkRouterProvider.get_clients
        tplinkrouterc6u.TplinkRouterProvider.get_clients = staticmethod(lambda: {"FakeEX": FakeEX})
        import nw.winapi
        self._unprotect = nw.winapi.unprotect
        nw.winapi.unprotect = lambda s: s

    def tearDown(self):
        import tplinkrouterc6u
        import nw.winapi
        tplinkrouterc6u.TplinkRouterProvider.get_clients = self._orig
        nw.winapi.unprotect = self._unprotect
        self.tmp.cleanup()

    def test_read_logs_out_and_normalises(self):
        snap = self.link.poll(manual=True)
        self.assertEqual(FakeEX.logins, 1)
        self.assertEqual(FakeEX.logouts, 1)
        self.assertEqual(snap["model"], "EX820v")
        self.assertEqual(snap["wan"]["ip"], "81.2.3.4")
        self.assertTrue(snap["wan"]["up"])
        self.assertEqual(snap["counts"]["total"], 7)
        self.assertEqual(snap["wifi"][1]["ssid"], "SKYCCF2E5-PRV")
        self.assertEqual(snap["wifi"][1]["guest_ssid"], "SKYCCF2E5")
        self.assertEqual([p["speed_mbps"] for p in snap["ports"]], [None, None, 100, 2500, 2500])
        self.assertNotIn("KeyPassphrase", str(snap["raw"]))
        kinds = {c["hostname"]: (c["kind"], c["band"]) for c in snap["clients"]}
        self.assertEqual(kinds["Hive-Hub"], ("wifi", "2.4 GHz"))
        self.assertEqual(kinds["Visitor-Phone"], ("guest", "5 GHz"))
        self.assertEqual(kinds["NAS"], ("wired", None))
        # enrichment: known device gets the router's hostname and connection type
        d = self.e.devices["AA:BB:CC:00:00:01"]
        self.assertEqual(d["hostname"], "DESKTOP-S5EOVAB")
        self.assertEqual(d["router_conn"], "Wired")
        self.assertTrue(any("LAN3" in m for _, _, m in self.e.events))
        v = self.link.view()
        self.assertEqual(sum(1 for c in v["clients"] if c["seen_by_scan"]), 1)
        self.assertTrue((Path(self.tmp.name) / "router_history.json").exists())

    def test_reboot_and_ip_change_events(self):
        self.link.poll(manual=True)
        FakeEX.uptime = 60
        orig = FakeEX.get_status

        def changed(selfx):
            s = orig(selfx)
            from ipaddress import IPv4Address
            s._wan_ipv4_addr = IPv4Address("81.2.3.99")
            return s
        FakeEX.get_status = changed
        try:
            self.link.poll(manual=True)
        finally:
            FakeEX.get_status = orig
            FakeEX.uptime = 3 * 86400
        msgs = " ".join(m for _, _, m in self.e.events)
        self.assertIn("Router restarted", msgs)
        self.assertIn("81.2.3.99", msgs)

    def test_stops_after_three_failed_logins(self):
        self.e.settings["router_password"] = "wrong"
        for _ in range(5):
            self.link.state["last_try"] = 0
            self.link.tick()
        self.assertEqual(FakeEX.logins, 3)
        self.assertTrue(self.link.state["suspended"])
        self.assertIn("rejected", self.link.state["error"])
        # changing the password clears the suspension
        self.e.settings["router_password"] = "secret"
        self.link.state["last_try"] = 0
        self.link.tick()
        self.assertFalse(self.link.state["suspended"])
        self.assertIsNotNone(self.link.snap)

    def test_backoff_and_pause(self):
        self.link.poll(manual=True)
        n = FakeEX.logins
        self.link.tick()  # not due yet
        self.assertEqual(FakeEX.logins, n)
        self.link.state["last_try"] = time.time() - 301
        self.link.pause(30)
        self.link.tick()  # paused
        self.assertEqual(FakeEX.logins, n)
        self.link.pause(0)
        self.link.tick()
        self.assertEqual(FakeEX.logins, n + 1)

    def test_ai_context_has_no_secrets(self):
        self.e.settings["router_password"] = "secret"
        self.link.poll(manual=True)
        ctx = self.link.ai_context()
        text = str(ctx)
        self.assertNotIn("should-be-scrubbed", text)
        self.assertNotIn("secret", text)
        self.assertEqual(ctx["router"]["model"], "EX820v")


if __name__ == "__main__":
    unittest.main()
