"""System tray icon (pystray) whose colour reflects connection health."""

import threading

try:
    import pystray
    from PIL import Image, ImageDraw
except ImportError:
    pystray = None

COLOURS = {"good": (34, 197, 94), "warn": (245, 158, 11), "bad": (239, 68, 68), "unknown": (148, 163, 184)}
TITLES = {"good": "Connection healthy", "warn": "Connected, with issues", "bad": "Internet is down",
          "unknown": "Starting"}


def make_icon(level="unknown", size=64):
    """Brand icon whose background colour shows connection health (drawn at 4x for smooth edges)."""
    import math
    from PIL import Image, ImageDraw
    pal = {"good": ((34, 211, 238), (99, 102, 241)), "warn": ((251, 191, 36), (234, 88, 12)),
           "bad": ((251, 113, 133), (190, 18, 60)), "unknown": ((148, 163, 184), (71, 85, 105))}
    c1, c2 = pal.get(level, pal["unknown"])
    k = size * 4
    grad = Image.new("RGBA", (k, k))
    px = grad.load()
    for y in range(k):
        for x in range(k):
            t = x / k * 0.55 + y / k * 0.45
            px[x, y] = tuple(int(c1[i] + (c2[i] - c1[i]) * t) for i in range(3)) + (255,)
    mask = Image.new("L", (k, k), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, k - 1, k - 1], radius=int(k * 0.23), fill=255)
    grad.putalpha(mask)
    d = ImageDraw.Draw(grad)
    s = k / 100 * 0.82
    ox = k * 0.09
    cx, cy, w = ox + 50 * s, ox + 70 * s, 9.5
    for r, a0, a1 in ((42, 225, 315), (28.5, 228, 312), (15, 233, 307)):
        R = (r + w / 2) * s
        d.arc([cx - R, cy - R, cx + R, cy + R], start=a0, end=a1, fill=(255, 255, 255, 255), width=int(w * s))
        for ang in (a0, a1):
            a = math.radians(ang)
            x, y = cx + r * s * math.cos(a), cy + r * s * math.sin(a)
            d.ellipse([x - w / 2 * s, y - w / 2 * s, x + w / 2 * s, y + w / 2 * s], fill=(255, 255, 255, 255))
    d.ellipse([cx - 7 * s, cy - 7 * s, cx + 7 * s, cy + 7 * s], fill=(255, 255, 255, 255))
    return grad.resize((size, size), Image.LANCZOS)


class Tray:
    def __init__(self, on_open, on_quit, on_speedtest, on_pause, on_overlay=None, on_about=None):
        self.available = pystray is not None
        self.icon = None
        self._handlers = (on_open, on_quit, on_speedtest, on_pause)
        self._overlay = on_overlay
        self._about = on_about

    def start(self):
        if not self.available:
            return
        on_open, on_quit, on_speed, on_pause = self._handlers
        menu = pystray.Menu(
            pystray.MenuItem("Open NetWatch", lambda: on_open(), default=True),
            pystray.MenuItem("Run speed test", lambda: on_speed()),
            pystray.MenuItem("Mini overlay", lambda: self._overlay(), visible=self._overlay is not None),
            pystray.MenuItem("Pause alerts", pystray.Menu(
                pystray.MenuItem("For 15 minutes", lambda: on_pause(15)),
                pystray.MenuItem("For 1 hour", lambda: on_pause(60)),
                pystray.MenuItem("For 8 hours", lambda: on_pause(480)),
                pystray.MenuItem("Resume alerts", lambda: on_pause(0)),
            )),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("About NetWatch", lambda: self._about(), visible=self._about is not None),
            pystray.MenuItem("Quit NetWatch", lambda: on_quit()),
        )
        self.icon = pystray.Icon("NetWatch", make_icon("unknown"), "NetWatch - starting", menu)
        threading.Thread(target=self.icon.run, daemon=True).start()

    def set_status(self, level):
        if self.icon:
            self.icon.icon = make_icon(level)
            self.icon.title = f"NetWatch - {TITLES.get(level, '')}"

    def notify(self, title, message):
        if self.icon:
            try:
                self.icon.notify(message, f"NetWatch · {title}")
            except Exception:
                pass

    def stop(self):
        if self.icon:
            try:
                self.icon.stop()
            except Exception:
                pass
