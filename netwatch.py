#!/usr/bin/env python3
"""
NetWatch 3 - a modern network monitor for Windows.

    pythonw netwatch.py              normal start
    pythonw netwatch.py --minimized  start hidden in the system tray (used by "Start with Windows")
    python  netwatch.py --browser    run the UI in your web browser instead of an app window
"""

import argparse
import hmac
import json
import os
import secrets
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from nw import winapi
from nw.api import Api
from nw.engine import Engine
from nw.tray import Tray
from nw.version import APP_NAME, VERSION

# Methods a phone on the local network may call (read-mostly; no admin, firewall or file actions)
LAN_ALLOWED = {
    "get_state", "get_devices", "scan_devices", "ping_device", "get_apps", "get_connections", "get_wifi", "get_dns",
    "get_services", "run_service_now", "start_speedtest", "get_speedtest", "start_traceroute", "stop_traceroute",
    "get_traceroute", "get_history", "get_events", "get_security", "get_troubleshoot", "run_troubleshoot",
    "run_tool", "get_tool", "get_usage", "get_timeline", "get_overnight", "get_apps_security", "get_world",
    "get_survey", "get_mesh", "get_dnsfilter", "get_sites", "pause_alerts", "ask", "run_security", "get_about",
    "get_router", "ask_router",
}


def resource_dir():
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base / "ui"


def data_dir():
    return Path(os.environ.get("APPDATA") or Path.home()) / "NetWatch"


def message_box(text):
    if winapi.IS_WINDOWS:
        import ctypes
        ctypes.windll.user32.MessageBoxW(None, text, "NetWatch", 0x40)
    else:
        print(text)


# --------------------------------------------------------------------------- HTTP server (browser & phone modes)
def make_server(api, engine, host, port, lan=False):
    ui = resource_dir()
    token = secrets.token_hex(16)
    lan_tokens = {}
    fails = {"n": 0, "until": 0}

    class Handler(SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(ui), **kw)

        def log_message(self, *a):
            pass

        def _send(self, code, body, ctype="application/json"):
            data = body if isinstance(body, bytes) else json.dumps(body, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def _body(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > 2_000_000:
                raise ValueError("too large")
            return json.loads(self.rfile.read(n) or b"null")

        def do_GET(self):
            if self.path.split("?")[0] == "/mode.js":
                js = (f"window.NW_BROWSER=true;window.NW_LAN={'true' if lan else 'false'};"
                      f"window.NW_TOKEN='{'' if lan else token}';")
                return self._send(200, js.encode(), "application/javascript")
            return super().do_GET()

        def do_POST(self):
            path = self.path.split("?")[0].strip("/")
            try:
                if path == "site/report":
                    ok = engine.extras.receive_site(self._body() or {}, self.headers.get("X-NW-Site-Key", ""))
                    return self._send(200 if ok else 403, {"ok": ok})
                if path == "auth" and lan:
                    if time.time() < fails["until"]:
                        return self._send(429, {"error": "Too many attempts - try again in a few minutes"})
                    pin = str((self._body() or {}).get("pin", ""))
                    real = winapi.unprotect(engine.settings.get("lan_pin", ""))
                    if real and hmac.compare_digest(pin, real):
                        t = secrets.token_hex(16)
                        lan_tokens[t] = time.time()
                        fails["n"] = 0
                        return self._send(200, {"token": t})
                    fails["n"] += 1
                    if fails["n"] >= 5:
                        fails.update(n=0, until=time.time() + 300)
                    return self._send(403, {"error": "Wrong PIN"})
                name = path.split("/")[-1]
                tok = self.headers.get("X-NW-Token", "")
                if lan:
                    if tok not in lan_tokens:
                        return self._send(401, {"error": "Please sign in again"})
                    if name not in LAN_ALLOWED:
                        return self._send(200, {"error": "That action is only available on the PC itself"})
                elif not hmac.compare_digest(tok, token):
                    return self._send(403, {"error": "forbidden"})
                if name.startswith("_") or not hasattr(api, name):
                    return self._send(404, {"error": "unknown"})
                args = self._body() or []
                return self._send(200, getattr(api, name)(*args))
            except Exception as e:
                return self._send(400, {"error": str(e)})

    server = ThreadingHTTPServer((host, port), Handler)
    server.daemon_threads = True
    return server


def local_ip():
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class LanService:
    """Phone dashboard + multi-site hub endpoint, bound to the local network."""

    def __init__(self, api, engine):
        self.api, self.engine = api, engine
        self.server = None

    def restart(self):
        self.stop()
        s = self.engine.settings
        st = self.engine.extras.lan_state
        if not (s.get("lan_enabled") or s.get("site_role") == "hub"):
            st.update(running=False, url=None, error=None)
            return
        if s.get("lan_enabled") and not s.get("lan_pin"):
            st.update(running=False, url=None, error="Set a PIN first")
            return
        port = int(s.get("lan_port") or 8780)
        try:
            self.server = make_server(self.api, self.engine, "0.0.0.0", port, lan=True)
        except OSError as e:
            st.update(running=False, url=None, error=f"Couldn't open port {port}: {e}")
            return
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        st.update(running=True, url=f"http://{local_ip()}:{port}/", error=None)

    def stop(self):
        if self.server:
            srv, self.server = self.server, None
            threading.Thread(target=srv.shutdown, daemon=True).start()


# --------------------------------------------------------------------------- single instance "bring to front"
def _port_file():
    return data_dir() / "instance.port"


def signal_running_instance(page=""):
    """Ask an already-running NetWatch to show its window. Returns True if it answered."""
    import socket
    try:
        port = int(_port_file().read_text().strip())
        with socket.create_connection(("127.0.0.1", port), timeout=2) as s:
            s.sendall(f"SHOW {page}\n".encode())
            return s.recv(16).startswith(b"OK")
    except Exception:
        return False


def listen_for_instances(on_show):
    import socket
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.bind(("127.0.0.1", 0))
    srv.listen(4)
    try:
        data_dir().mkdir(parents=True, exist_ok=True)
        _port_file().write_text(str(srv.getsockname()[1]))
    except OSError:
        pass

    def loop():
        while True:
            try:
                c, _ = srv.accept()
            except OSError:
                return
            with c:
                try:
                    c.settimeout(2)
                    msg = c.recv(64).decode(errors="ignore").strip()
                    if msg.startswith("SHOW"):
                        c.sendall(b"OK")
                        on_show(msg[4:].strip())
                except OSError:
                    pass
    threading.Thread(target=loop, daemon=True).start()
    return srv


# --------------------------------------------------------------------------- main
def main():
    parser = argparse.ArgumentParser(description="NetWatch network monitor")
    parser.add_argument("--minimized", action="store_true")
    parser.add_argument("--browser", action="store_true")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-open", action="store_true")
    parser.add_argument("--page", default="", help="open on a page, e.g. --page about")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {VERSION}")
    args = parser.parse_args()

    if not winapi.acquire_single_instance():
        if args.minimized:  # started by "Start with Windows" while already running - nothing to do
            return
        if not signal_running_instance(args.page):
            message_box("NetWatch is already running. Look for its icon in the system tray (near the clock).")
        return

    engine = Engine(data_dir())
    state = {"quitting": False, "window": None, "overlay": None}

    try:
        import webview  # noqa: F401
        have_webview = not args.browser
    except ImportError:
        have_webview = False

    def show(page=""):
        w = state["window"]
        if w:
            w.show()
            w.restore()
            try:
                w.on_top = True
                w.on_top = False  # nudge to the foreground
            except Exception:
                pass
            if page:
                try:
                    w.evaluate_js(f"go({json.dumps(page)})")
                except Exception:
                    pass
        else:
            webbrowser.open(state.get("url", "") + (f"#{page}" if page else ""))

    def quit_app():
        if state["quitting"]:
            return
        state["quitting"] = True
        engine.stop()
        lan.stop()
        tray.stop()
        if state["overlay"]:
            try:
                state["overlay"].destroy()
            except Exception:
                pass
        if state["window"]:
            state["window"].destroy()
        if state.get("server"):
            threading.Thread(target=state["server"].shutdown, daemon=True).start()

    def toggle_overlay():
        if not have_webview:
            return False
        import webview
        if state["overlay"]:
            try:
                state["overlay"].destroy()
            except Exception:
                pass
            state["overlay"] = None
            return False
        x = y = None
        try:
            scr = webview.screens[0]
            x, y = scr.width - 330, scr.height - 170
        except Exception:
            pass
        state["overlay"] = webview.create_window(
            "NetWatch mini", url=str(resource_dir() / "overlay.html"), js_api=api, width=310, height=104,
            x=x, y=y, frameless=True, on_top=True, easy_drag=True, resizable=False, background_color="#0b1124")
        state["overlay"].events.closed += lambda: state.update(overlay=None)
        return True

    api = Api(engine, quit_cb=quit_app)
    lan = LanService(api, engine)
    engine.extras.ui_hooks.update(lan_restart=lan.restart, toggle_overlay=toggle_overlay)
    tray = Tray(lambda: show(), quit_app, lambda: engine.start_speedtest("manual"), lambda m: api.pause_alerts(m),
                on_overlay=toggle_overlay if have_webview else None, on_about=lambda: show("about"))
    instance_srv = listen_for_instances(show)
    engine.notify_cb = tray.notify
    engine.status_cb = tray.set_status
    tray.start()
    engine.start()
    lan.restart()

    if have_webview:
        import webview
        start_url = (resource_dir() / "index.html").as_uri() + (f"#{args.page}" if args.page else "")
        window = webview.create_window(
            APP_NAME, url=start_url, js_api=api,
            width=1440, height=920, min_size=(1100, 720), hidden=args.minimized,
            background_color="#070b18", text_select=False)
        state["window"] = window
        api._set_window(window)

        def on_closing():
            if not state["quitting"] and engine.settings.get("minimize_to_tray", True) and tray.available:
                window.hide()
                if not state.get("hint_shown"):
                    state["hint_shown"] = True
                    tray.notify("Still running", "NetWatch is still monitoring in the background. "
                                "Right-click the tray icon to quit.")
                return False
            if not state["quitting"]:
                quit_app()
            return True

        def on_started():
            if engine.settings.get("overlay_on_start"):
                toggle_overlay()

        window.events.closing += on_closing
        webview.start(on_started, private_mode=False, storage_path=str(data_dir() / "webview"))
        if not state["quitting"]:
            quit_app()
    else:
        server = make_server(api, engine, "127.0.0.1", args.port)
        state["server"] = server
        url = f"http://127.0.0.1:{server.server_address[1]}/index.html"
        state["url"] = url
        print(f"NetWatch UI running at {url}  (Ctrl+C to stop)")
        if not (args.minimized or args.no_open):
            threading.Timer(0.8, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            if not state["quitting"]:
                quit_app()
    winapi.release_single_instance()


if __name__ == "__main__":
    main()
