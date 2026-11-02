from __future__ import annotations

import glob
import re
import shutil
import subprocess
import threading
import time

from .notify import Notification

SERVICE = "org.kde.kdeconnect"
DEVICES_PATH = "/modules/kdeconnect/devices"
NOTIFICATIONS_IFACE = "org.kde.kdeconnect.device.notifications"
NOTIFICATION_IFACE = "org.kde.kdeconnect.device.notifications.notification"

NODE = re.compile(r"^\s*node\s+(\S+)\s*\{", re.M)
QUOTED = re.compile(r"'((?:[^'\\]|\\.)*)'")
FALLBACK_GDBUS = "/opt/homebrew/bin/gdbus"


class KdeConnectSource:
    def __init__(self, notifier, interval=2.0):
        self.notifier = notifier
        self.interval = interval
        self.gdbus = shutil.which("gdbus") or (
            FALLBACK_GDBUS if shutil.which(FALLBACK_GDBUS) else None
        )
        self.bus = None
        self.devices = []
        self.detail = "not started"
        self._seen = {}
        self._primed = set()
        self._stop = threading.Event()

    def start(self):
        if not self.gdbus:
            self.detail = "gdbus introuvable (installez glib : brew install glib)"
            return
        threading.Thread(target=self._loop, name="wled-kdeconnect", daemon=True).start()

    def stop(self):
        self._stop.set()

    def status(self):
        return {
            "available": bool(self.gdbus),
            "bus": self.bus,
            "devices": self.devices,
            "detail": self.detail,
        }

    def _run(self, address, args, timeout=5):
        try:
            done = subprocess.run(
                [self.gdbus, *args],
                env={"DBUS_SESSION_BUS_ADDRESS": f"unix:path={address}", "PATH": "/usr/bin:/bin"},
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        return done.stdout if done.returncode == 0 else None

    def _find_bus(self):
        for socket in sorted(glob.glob("/tmp/dbus-*")):
            names = self._run(socket, [
                "call", "--session", "--dest", "org.freedesktop.DBus",
                "--object-path", "/org/freedesktop/DBus",
                "--method", "org.freedesktop.DBus.ListNames",
            ], timeout=3)
            if names and SERVICE in names:
                return socket
        return None

    def _list_devices(self):
        tree = self._run(self.bus, [
            "introspect", "--session", "--dest", SERVICE, "--object-path", DEVICES_PATH,
        ])
        if not tree:
            return []
        return [name for name in NODE.findall(tree) if name != DEVICES_PATH]

    def _active(self, device):
        raw = self._run(self.bus, [
            "call", "--session", "--dest", SERVICE,
            "--object-path", f"{DEVICES_PATH}/{device}/notifications",
            "--method", f"{NOTIFICATIONS_IFACE}.activeNotifications",
        ])
        return QUOTED.findall(raw) if raw else []

    def _property(self, device, public_id, name):
        raw = self._run(self.bus, [
            "call", "--session", "--dest", SERVICE,
            "--object-path", f"{DEVICES_PATH}/{device}/notifications/{public_id}",
            "--method", "org.freedesktop.DBus.Properties.Get",
            NOTIFICATION_IFACE, name,
        ])
        if not raw:
            return ""
        found = QUOTED.search(raw)
        return found.group(1).replace("\\'", "'") if found else ""

    def _loop(self):
        while not self._stop.wait(self.interval):
            if not self.bus:
                self.bus = self._find_bus()
                if not self.bus:
                    self.detail = "KDE Connect introuvable sur le bus D-Bus"
                    continue

            devices = self._list_devices()
            if not devices:
                self.detail = "no paired device visible"
                self.bus = None
                continue

            self.devices = devices
            self.detail = f"watching {len(devices)} device(s)"
            for device in devices:
                self._scan(device)

    def _scan(self, device):
        current = set(self._active(device))
        known = self._seen.get(device, set())
        self._seen[device] = current

        if device not in self._primed:
            self._primed.add(device)
            return

        for public_id in sorted(current - known):
            app = self._property(device, public_id, "appName")
            title = self._property(device, public_id, "title")
            if not app:
                continue
            self.notifier.submit(Notification(
                priority=0,
                received=time.time(),
                source="kdeconnect",
                app=app,
                title=title,
            ))
