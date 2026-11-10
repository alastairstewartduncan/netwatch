"""Remote alert channels: email (SMTP), Microsoft Teams (Workflows webhook) and phone push (ntfy)."""

import json
import smtplib
import ssl
import time
import urllib.request
from email.message import EmailMessage

from .winapi import unprotect

LEVELS = {"INFO": 0, "OK": 1, "WARN": 2, "ALERT": 3}


def send_email(cfg, title, message):
    msg = EmailMessage()
    msg["Subject"] = f"[NetWatch] {title}"
    msg["From"] = cfg.get("smtp_from") or cfg.get("smtp_user")
    msg["To"] = cfg["email_to"]
    msg.set_content(f"{message}\n\nSent by NetWatch at {time.strftime('%Y-%m-%d %H:%M:%S')}")
    host, port = cfg["smtp_host"], int(cfg.get("smtp_port") or 587)
    password = unprotect(cfg.get("smtp_password", ""))
    ctx = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(host, port, context=ctx, timeout=20) as s:
            if cfg.get("smtp_user"):
                s.login(cfg["smtp_user"], password)
            s.send_message(msg)
    else:
        with smtplib.SMTP(host, port, timeout=20) as s:
            s.ehlo()
            if s.has_extn("starttls"):
                s.starttls(context=ctx)
                s.ehlo()
            if cfg.get("smtp_user"):
                s.login(cfg["smtp_user"], password)
            s.send_message(msg)


def send_teams(cfg, title, message, level):
    colour = {"ALERT": "Attention", "WARN": "Warning", "OK": "Good"}.get(level, "Default")
    card = {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard", "version": "1.4",
                "body": [
                    {"type": "TextBlock", "text": f"NetWatch · {title}", "weight": "Bolder",
                     "size": "Medium", "color": colour},
                    {"type": "TextBlock", "text": message, "wrap": True},
                    {"type": "TextBlock", "text": time.strftime("%Y-%m-%d %H:%M:%S"),
                     "isSubtle": True, "size": "Small"},
                ],
            },
        }],
    }
    req = urllib.request.Request(cfg["teams_webhook"], data=json.dumps(card).encode(),
                                 headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=15).read()


def send_ntfy(cfg, title, message, level):
    server = (cfg.get("ntfy_server") or "https://ntfy.sh").rstrip("/")
    priority = {"ALERT": "high", "WARN": "default", "OK": "low"}.get(level, "low")
    tags = {"ALERT": "rotating_light", "WARN": "warning", "OK": "white_check_mark"}.get(level, "information_source")
    req = urllib.request.Request(f"{server}/{cfg['ntfy_topic']}", data=message.encode("utf-8"),
                                 headers={"Title": f"NetWatch: {title}", "Priority": priority, "Tags": tags})
    urllib.request.urlopen(req, timeout=15).read()


class RemoteNotifier:
    def __init__(self, get_cfg, on_error):
        self.get_cfg = get_cfg
        self.on_error = on_error
        self._recent = {}

    def send(self, level, title, message, force=False):
        cfg = self.get_cfg()
        if not force:
            if LEVELS.get(level, 0) < LEVELS.get(cfg.get("min_level", "ALERT"), 3):
                return
            key = message
            now = time.time()
            if now - self._recent.get(key, 0) < 600:  # de-duplicate within 10 minutes
                return
            self._recent[key] = now
        results = {}
        for name, enabled, fn in (
            ("email", cfg.get("email_enabled") and cfg.get("smtp_host") and cfg.get("email_to"),
             lambda: send_email(cfg, title, message)),
            ("teams", cfg.get("teams_enabled") and cfg.get("teams_webhook"),
             lambda: send_teams(cfg, title, message, level)),
            ("ntfy", cfg.get("ntfy_enabled") and cfg.get("ntfy_topic"),
             lambda: send_ntfy(cfg, title, message, level)),
        ):
            if not enabled:
                continue
            try:
                fn()
                results[name] = "sent"
            except Exception as e:
                results[name] = f"failed: {e}"
                if not force:
                    self.on_error(f"{name} alert failed: {e}")
        return results
