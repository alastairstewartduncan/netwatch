"""Single source of truth for NetWatch's product identity, version and release notes.

Change PUBLISHER / COPYRIGHT here and everything else - the app, the About page, the .exe's file properties,
the installer and Add/Remove Programs - picks it up at build time.
"""

APP_NAME = "NetWatch"
VERSION = "3.2.0"
BUILD_DATE = "2026-11-13"
CHANNEL = "Stable"
PUBLISHER = "Alastair Duncan"
COPYRIGHT = "© 2026 Alastair Duncan"
DESCRIPTION = "Network monitor for Windows"
APP_ID = "AlastairDuncan.NetWatch"  # Windows AppUserModelID - groups taskbar icon & notifications
UPDATE_REPO_DEFAULT = "alastairstewartduncan/netwatch"  # e.g. "your-github-name/netwatch" to switch on auto-update for everyone

# Newest first. Each change is a short, user-facing sentence.
CHANGELOG = [
    {"version": "3.2.0", "date": "2026-11-13", "title": "Router integration", "changes": [
        "New Router page: NetWatch signs in to your TP-Link router (including ISP-supplied EX and VR models) and reads its status directly",
        "See broadband link, public IP, uptime, firmware, CPU and memory, Wi-Fi bands and channels, and every connected device",
        "Ethernet port diagram showing the speed each port negotiated, with a warning when a cable is holding a device back",
        "Charts of connected devices and router load over time",
        "Router insights: one-click AI health check of your router, plus questions about ports, Wi-Fi and devices",
        "Ask NetWatch now includes router data; device list gains the router's names and wired/2.4/5 GHz connection type",
        "Alerts for router restarts, broadband IP changes and the router reporting its broadband link down",
        "Read-only and lockout-safe: signs in, reads and signs out every 5 minutes, and stops after 3 failed sign-ins",
    ]},
    {"version": "3.1.0", "date": "2026-11-10", "title": "The finished product", "changes": [
        "Proper Windows installer with Start menu and desktop shortcuts, and uninstall from Settings → Apps",
        "New About page: version, what's new, system information, licences and update check",
        "First-run setup that asks for your broadband plan and preferences",
        "Loading screen, refreshed app icon and full file details in the .exe",
        "Updates now download and run the installer, so they work for standard users too",
        "Installer allows the phone dashboard through Windows Firewall and checks for the WebView2 runtime",
    ]},
    {"version": "3.0.0", "date": "2026-11-09", "title": "Security, diagnostics and integrations", "changes": [
        "Security page: router port-forward audit, internet exposure check, this-PC review, ARP spoofing and rogue DHCP detection",
        "Troubleshooter with one-click fixes",
        "Video call, gaming and streaming quality scores; bufferbloat grading in speed tests",
        "Microsoft 365, cloud latency, 'Is it just me?' and IPv6 tests",
        "Data usage with data-cap alerts and an overnight activity report",
        "Trusted devices, device timeline, inventory export and printer/NAS health (SNMP)",
        "New-app alerts, app blocking, websites contacted, tracker detection and world map",
        "VPN drop alerts and leak test, captive portal and open Wi-Fi warnings, backup-line detection",
        "Wi-Fi room survey and mesh roaming history",
        "Smart anomaly alerts, quiet hours, certificate expiry warnings and weekly summary",
        "Home Assistant (MQTT), Pi-hole / AdGuard Home, Ask NetWatch AI assistant",
        "Phone dashboard with PIN, mini overlay, multi-site mode and auto-update",
    ]},
    {"version": "2.0.0", "date": "2026-11-09", "title": "A modern redesign", "changes": [
        "All-new dark and light dashboard interface",
        "System tray icon and start with Windows",
        "Scheduled speed tests against your broadband plan",
        "90-day history and printable ISP complaint report",
        "Wi-Fi signal, channel congestion and nearby networks",
        "Device network map, manufacturer lookup, port scan and Wake-on-LAN",
        "Website and service checks, visual traceroute and DNS comparison",
        "Email, Microsoft Teams and phone push alerts",
        "Per-app bandwidth (as administrator)",
    ]},
    {"version": "1.0.0", "date": "2026-11-09", "title": "First release", "changes": [
        "Internet status, latency and packet loss to several targets",
        "Live bandwidth charts",
        "Device discovery with new-device alerts",
        "Active connections by process",
        "Event log with CSV export",
    ]},
]

CREDITS = [
    ("Python", "Python Software Foundation License", "https://www.python.org/"),
    ("pywebview", "BSD-3-Clause", "https://pywebview.flowrl.com/"),
    ("psutil", "BSD-3-Clause", "https://github.com/giampaolo/psutil"),
    ("pystray", "LGPL-3.0", "https://github.com/moses-palmer/pystray"),
    ("Pillow", "MIT-CMU (HPND)", "https://python-pillow.org/"),
    ("openpyxl", "MIT", "https://openpyxl.readthedocs.io/"),
    ("Chart.js", "MIT", "https://www.chartjs.org/"),
    ("tplinkrouterc6u", "GPL-3.0-or-later", "https://github.com/AlexandrErohin/TP-Link-Archer-C6U"),
    ("requests", "Apache-2.0", "https://requests.readthedocs.io/"),
    ("PyCryptodome", "BSD-2-Clause / Public domain", "https://www.pycryptodome.org/"),
    ("macaddress", "0BSD", "https://github.com/mentalisttraceur/python-macaddress"),
    ("world-atlas / Natural Earth", "ISC / Public domain", "https://github.com/topojson/world-atlas"),
    ("Microsoft Edge WebView2", "Microsoft Software License", "https://developer.microsoft.com/microsoft-edge/webview2/"),
]

SERVICES = [
    ("Cloudflare", "Speed tests and public IP", "https://speed.cloudflare.com/"),
    ("IEEE Registration Authority", "Device manufacturer database", "https://standards.ieee.org/"),
    ("Shodan InternetDB", "Internet exposure check", "https://internetdb.shodan.io/"),
    ("ip-api.com", "World map locations (opt-in)", "https://ip-api.com/"),
    ("Anthropic Claude", "Ask NetWatch assistant (opt-in)", "https://www.anthropic.com/"),
    ("ntfy", "Phone push alerts (opt-in)", "https://ntfy.sh/"),
]


def version_tuple(v=VERSION):
    parts = [int(x) for x in v.split(".")[:3]]
    return tuple(parts + [0] * (4 - len(parts)))
