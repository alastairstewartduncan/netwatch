# NetWatch — Network Monitor for Windows

A modern desktop app that watches your internet connection, home network and the devices on it — and tells you when something goes wrong.

## Features

| Area | What you get |
|---|---|
| **Dashboard** | Live health banner (good / issues / down), latency, packet loss, jitter, download/upload, Wi-Fi signal and DNS gauges, live charts, device mix, last speed test, health check and recent events. |
| **Devices** | Finds everything on your network. Grid, list and **network map** views. Manufacturer lookup (IEEE database), automatic device-type icons, rename/notes, ping, **port scan** with risky-port warnings, **Wake-on-LAN**, open a device's web page. Alerts when an **unknown device joins**. |
| **Apps & traffic** | **Per-app live bandwidth** and today's totals (run as administrator), plus every active connection by app. |
| **Wi-Fi** | Signal %, RSSI, band, channel, link rate, signal history, **channel congestion chart**, nearby networks and a best-channel recommendation. Alerts on drop-outs and weak signal. |
| **Speed test** | Animated speedometer, download/upload/ping/jitter via Cloudflare's speed test (no account needed). **Scheduled tests**, history chart and comparison against your broadband plan, with an alert when speeds fall short. |
| **Services** | Monitor websites (HTTP/S), TCP ports and pingable hosts — uptime %, response-time sparklines and up/down alerts. |
| **DNS** | Times your own DNS server against Cloudflare, Google and Quad9, warns when DNS fails, and suggests a faster option. |
| **Traceroute** | Visual hop-by-hop route with latency bars, highlights where the delay is added. |
| **History & reports** | Up to 90 days of history: uptime per day, outages with likely cause (router vs ISP), latency/loss and bandwidth charts. Export CSV or a printable **ISP complaint report**. |
| **Alerts** | Desktop notifications, plus **email**, **Microsoft Teams** and **phone push (ntfy)**. Pause alerts from the app or tray. |
| **Tray & startup** | Lives in the system tray (icon colour = connection health), keeps monitoring when closed, optional **start with Windows**. |
| **Look & feel** | Dark and light themes, modern dashboard UI. |

## New in 3.1

Windows installer and uninstaller, About page with version, release history, system info and licences, first-run setup, "What's new" after updates, loading screen, new app icon, and updates that run the installer.

## New in 3.0

| Area | What's new |
|---|---|
| **Troubleshooter** | One-click check from adapter → Wi-Fi → router → internet → DNS → web → IPv6, pinpoints where it breaks, with fixes (flush DNS, renew IP, restart adapter, reset network stack, switch to Cloudflare DNS). |
| **Quality scores** | Live ratings for video calls (MOS), gaming and streaming on the dashboard. |
| **Bufferbloat** | Every speed test measures latency under load and grades it A+ to F. |
| **Security page** | Router port-forward audit (UPnP), internet exposure check (Shodan InternetDB), this-PC review (firewall, Defender, RDP, SMBv1, listening ports), ARP-spoofing and rogue-DHCP detection, security score. |
| **Trusted devices** | Mark devices trusted; untrusted ones are highlighted and reported when they return. |
| **Quiet hours** | Only outages and security alerts pop up overnight. |
| **Smart alerts** | Learns normal latency, loss and DNS per hour of day and flags anomalies. |
| **Apps** | New-app alerts with code-signature check, one-click firewall block, websites each app contacts with trackers highlighted, world map of connections (opt-in). |
| **Traffic capture** | Record 30 s – 5 min to a Wireshark-ready .pcapng (built-in pktmon). |
| **VPN** | Drop alerts and a DNS/IP leak test. Open Wi-Fi and captive-portal warnings. Backup-line (4G/5G failover) detection. |
| **More tests** | Microsoft 365 connectivity, cloud/game server latency, “Is it just me?”, IPv6 health. |
| **Data usage** | Daily/monthly totals, billing cycle, data-cap alerts, projection, overnight activity report. |
| **Devices** | Online timeline (24 h / 7 days), inventory export to Excel/CSV/PDF, SNMP health for printers and NAS. |
| **Wi-Fi** | Room-by-room survey, access-point and roaming history for mesh systems. |
| **Services** | TLS certificate expiry warnings. |
| **Reports** | Downtime cost on the History page; weekly summary via email/Teams/phone. |
| **Integrations** | Home Assistant (MQTT auto-discovery incl. device presence), Pi-hole / AdGuard Home stats, Ask NetWatch (Claude AI assistant). |
| **Access** | Phone dashboard with PIN, mini always-on-top overlay, multi-site hub/agent mode, auto-update from GitHub releases. |

### Things that need you to switch them on (Settings)
- **Ask NetWatch** – an Anthropic API key (Integrations).
- **Home Assistant** – your MQTT broker (Integrations).
- **Pi-hole / AdGuard** – its address and password (Integrations).
- **Printer / NAS health** – SNMP enabled on the device.
- **Phone dashboard** – turn on and set a PIN (Phone & sites). Allow NetWatch through Windows Firewall on *Private* networks when asked.
- **Multi-site** – one PC as hub, others as agents with the same site key.
- **Auto-update** – a GitHub repo where you publish `NetWatch.exe` as a release asset.
- **World map** – sends connection IPs to ip-api.com, so it's off until you enable it.
- **Admin-only features** – per-app bandwidth, app blocking, traffic capture and some fixes. Use *Restart as administrator* on the Apps page.

## Building & installing

**Build the installer (on Windows)**
1. Install **Python 3.12** from python.org and tick **Add python.exe to PATH**.
2. Double-click **`build.bat`**. It installs everything it needs (including NSIS, the installer builder, via winget) and after a few minutes opens the `dist` folder with:
   - **`NetWatch-Setup-3.1.0.exe`** — the installer. This is the file to run or give to people.
   - `NetWatch-3.1.0-portable.zip` — a no-install copy.
   - `NetWatch\NetWatch.exe` — the app itself.
3. Run the installer. It adds NetWatch to the Start menu (and optionally the desktop), can start it when you sign in, allows the phone dashboard through Windows Firewall on private networks, checks for the WebView2 runtime, and registers in **Settings → Apps** for clean uninstalling. Upgrading keeps your settings and history; uninstalling asks whether to keep them.

**Windows SmartScreen:** the installer isn't code-signed, so Windows may say "Windows protected your PC" the first time. Click **More info → Run anyway**. To sign it, set `NETWATCH_SIGN_CERT` (a .pfx path) and `NETWATCH_SIGN_PASSWORD` before building.

**Installer switches:** `/S` silent install · `/D=C:\path` install folder · uninstall silently with `"Uninstall NetWatch.exe" /S`.

**Run from source:** double-click `run.bat`.

## Releasing updates

1. Change `VERSION` and add a `CHANGELOG` entry in **`nw/version.py`**. That one file feeds the app, the About page, the .exe properties and the installer.
2. Push the project to GitHub and tag it: `git tag v3.1.1 && git push --follow-tags`. The included workflow (`.github/workflows/release.yml`) builds the installer on GitHub's Windows machines and publishes a release.
3. Set the repository in NetWatch → Settings → Data & updates (or in `UPDATE_REPO_DEFAULT` in `nw/version.py` so every copy has it). NetWatch then checks every 6 hours, offers the update, downloads the installer and upgrades itself with one approval prompt.

To change the publisher name or copyright, edit `PUBLISHER` / `COPYRIGHT` in `nw/version.py`. To redraw the icon and installer artwork, run `python tools/make_art.py`.

## Tips

- **Per-app bandwidth** needs administrator rights (Windows only exposes per-connection counters to elevated apps). Use the *Restart as administrator* button on the Apps page.
- **Wi-Fi details** on Windows 11 24H2+ require *Settings → Privacy & security → Location* to be on, with desktop apps allowed.
- Set your **broadband plan speeds** in Settings so speed tests and reports show "% of plan".
- **Teams alerts:** in the channel, choose ⋯ → *Workflows* → "Post to a channel when a webhook request is received", and paste the URL into Settings.
- **Phone alerts:** install the free **ntfy** app, subscribe to a hard-to-guess topic and enter the same topic in Settings.
- Automatic speed tests use roughly 200–500 MB each on fast connections — adjust the interval in Settings.
- If the app window won't open (WebView2 missing), run `NetWatch.exe --browser` (or `python netwatch.py --browser`) to use the interface in your web browser.

## Where data lives

`%APPDATA%\NetWatch` — `settings.json`, `history.db` (SQLite), the vendor database and `error.log`. The email password is encrypted with your Windows account (DPAPI).

## Project layout

```
netwatch.py        entry point (app window, tray, browser mode)
nw/engine.py       monitoring engine: workers, alerts, state
nw/netops.py       discovery, vendors, port scan, WoL, traceroute, DNS, Wi-Fi, checks
nw/winapi.py       native Windows APIs (ICMP, per-app TCP stats, DPAPI, startup)
nw/speedtest.py    Cloudflare speed test
nw/storage.py      SQLite history
nw/alerts.py       email / Teams / ntfy
nw/api.py          bridge between the UI and the engine, ISP report
nw/tray.py         system tray icon
nw/extras.py       v3 feature manager (presence, anomalies, VPN, apps, usage, sites…)
nw/security.py     UPnP audit, exposure, spoofing/DHCP, PC check, firewall, capture
nw/diag.py         troubleshooter, quality, bufferbloat, M365, cloud, IPv6, DNS cache
nw/integrations.py MQTT/Home Assistant, Pi-hole/AdGuard, SNMP, Claude, updater
nw/version.py      version, publisher, changelog, credits (single source of truth)
ui/                HTML/CSS/JS interface (Chart.js bundled for offline use)
installer/         NSIS installer script
tools/             build.py, make_version_info.py, make_art.py
assets/            app icon and installer artwork
.github/workflows/ automatic release builds
```

Only scan networks you own or manage.
