"""Checks whether NetWatch can read your router, before you build or release.

    python tools/router_probe.py                 (uses your default gateway, username 'admin')
    python tools/router_probe.py 192.168.0.1 --user user

It signs in once per method it tries (at most 4), reads everything NetWatch would, signs out, and writes
router_probe.json next to this script. Passwords and Wi-Fi keys are removed from that file, so you can
share it. It never changes anything on the router.
"""

import argparse
import getpass
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from tplinkrouterc6u import TplinkRouterProvider
except ImportError:
    print("Installing tplinkrouterc6u…")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet", "tplinkrouterc6u"])
    from tplinkrouterc6u import TplinkRouterProvider

from nw.router import EX_CLIENTS, PORT_OIDS, _scrub, parse_ports  # noqa: E402

EXTRA_OIDS = ("DEV2_ADT_WIFI_COMMON", "DEV2_ADT_WAN", "DEV2_ADT_LAN", "DEV2_HOST_ENTRY", "DEV2_MEM_STATUS",
              "DEV2_PROC_STATUS") + PORT_OIDS


def gateway():
    try:
        out = subprocess.run(["route", "print", "0.0.0.0"], capture_output=True, text=True, timeout=10).stdout
        for line in out.splitlines():
            p = line.split()
            if len(p) >= 3 and p[0] == "0.0.0.0" and p[1] == "0.0.0.0":
                return p[2]
    except Exception:
        pass
    return "192.168.0.1"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("host", nargs="?", default=None)
    ap.add_argument("--user", default="admin")
    a = ap.parse_args()
    host = a.host or gateway()
    url = host if host.startswith("http") else f"http://{host}"
    pw = getpass.getpass(f"Admin password for {url}: ")
    report = {"host": url, "user": a.user, "tried": []}
    clients = TplinkRouterProvider.get_clients()
    router = None
    for name in [n for n in EX_CLIENTS if n in clients] + ["TplinkRouter"]:
        r = clients[name](url, pw, a.user, None, False, 15)
        try:
            r.authorize()
        except Exception as ex:
            report["tried"].append({"client": name, "error": str(ex)[:300]})
            print(f"  {name}: no ({str(ex)[:120]})")
            if "password" in str(ex).lower():
                print("\nThe router rejected the password. Check it, or try --user user. Stopping so the account "
                      "doesn't get locked.")
                break
            continue
        print(f"  {name}: signed in")
        report["client"] = name
        router = r
        break
    if router is None:
        Path(ROOT / "tools" / "router_probe.json").write_text(json.dumps(report, indent=2))
        print("\nCouldn't sign in. Details saved to tools/router_probe.json")
        return 1
    try:
        for label, fn in (("firmware", "get_firmware"), ("status", "get_status"), ("ipv4", "get_ipv4_status"),
                          ("leases", "get_ipv4_dhcp_leases")):
            try:
                report[label] = repr(getattr(router, fn)())[:6000]
                print(f"  {label}: ok")
            except Exception as ex:
                report[label] = f"ERROR {ex}"
                print(f"  {label}: failed ({ex})")
        if hasattr(router, "req_act"):
            report["oids"] = {}
            for oid in EXTRA_OIDS:
                for op in ("gl", "go"):
                    try:
                        _, vals = router.req_act([router.ActItem(op, oid)])
                        report["oids"][f"{op} {oid}"] = _scrub(vals[0] if vals else None)
                        print(f"  {op} {oid}: {'data' if vals and vals[0] else 'empty'}")
                        break
                    except Exception as ex:
                        report["oids"][f"{op} {oid}"] = f"ERROR {str(ex)[:200]}"
            for oid in PORT_OIDS:
                v = report["oids"].get(f"gl {oid}") or report["oids"].get(f"go {oid}")
                if v and not isinstance(v, str):
                    report["ports"] = parse_ports(v)
                    print(f"\nEthernet ports via {oid}: {report['ports']}")
                    break
            else:
                print("\nNo per-port link speeds found with the known names - the rest still works.")
    finally:
        try:
            router.logout()
        except Exception:
            pass
    out = ROOT / "tools" / "router_probe.json"
    out.write_text(json.dumps(report, indent=2, default=str))
    print(f"\nSaved {out} (no passwords in it).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
