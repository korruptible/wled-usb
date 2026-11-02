from __future__ import annotations

import json
import pathlib
import queue
import threading
import time
from dataclasses import dataclass, field

from .bridge import replayable
from .link import LinkError

DEFAULTS = {
    "enabled": True,
    "notifyWhenOff": True,
    "coalesceSeconds": 6,
    "maxQueue": 12,
    "defaultPattern": "info",
    "quietHours": None,
    "powerBudgetMa": 700,
    "ledMilliamps": 55,
    "baseMilliamps": 100,
    "patterns": {
        "slack": {"color": [74, 168, 255], "leds": 20, "flashes": 3, "onMs": 220, "offMs": 150, "bri": 140},
        "message": {"color": [120, 255, 140], "leds": 20, "flashes": 2, "onMs": 240, "offMs": 160, "bri": 130},
        "urgent": {"color": [255, 40, 40], "leds": 30, "flashes": 5, "onMs": 160, "offMs": 110, "bri": 150},
        "call": {"color": [0, 230, 118], "leds": 30, "flashes": 8, "onMs": 180, "offMs": 140, "bri": 150},
        "info": {"color": [255, 180, 60], "leds": 16, "flashes": 2, "onMs": 260, "offMs": 180, "bri": 130},
    },
    "rules": [
        {"app": "Slack", "pattern": "slack", "priority": 30},
        {"app": "Messenger", "pattern": "message", "priority": 10},
        {"app": "Signal", "pattern": "message", "priority": 15},
        {"app": "WhatsApp", "pattern": "message", "priority": 15},
        {"app": "Téléphone", "pattern": "call", "priority": 50},
        {"app": "Phone", "pattern": "call", "priority": 50},
    ],
    "ignore": [],
}


@dataclass(order=True)
class Notification:
    priority: int
    received: float = field(compare=False)
    source: str = field(compare=False, default="http")
    app: str = field(compare=False, default="")
    title: str = field(compare=False, default="")
    body: str = field(compare=False, default="")
    pattern: str = field(compare=False, default="")

    def key(self):
        return (self.source, self.app.lower(), self.title)


class Notifier:
    def __init__(self, bridge, config_path):
        self.bridge = bridge
        self.path = pathlib.Path(config_path)
        self.config = self._load()
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._log = []
        self._recent = {}
        self._stop = threading.Event()
        self.playing = None
        self.audio = None

    def _load(self):
        merged = json.loads(json.dumps(DEFAULTS))
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return merged
        if isinstance(stored, dict):
            merged.update(stored)
        return merged

    def save(self, config=None):
        with self._lock:
            if config is not None:
                self.config = config
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.config, indent=1, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self.path)
        return self.config

    def start(self):
        threading.Thread(target=self._worker, name="wled-notify", daemon=True).start()

    def stop(self):
        self._stop.set()
        self._queue.put(None)

    def submit(self, notification):
        verdict = self._screen(notification)
        if verdict != "accepted":
            self._record(notification, verdict)
            return verdict
        if self._queue.qsize() >= self.config.get("maxQueue", 12):
            self._record(notification, "file pleine")
            return "dropped"
        self._queue.put(notification)
        return "accepted"

    def _screen(self, notification):
        if not self.config.get("enabled", True):
            return "désactivé"
        if self._in_quiet_hours():
            return "heures calmes"
        app = notification.app.lower()
        for entry in self.config.get("ignore", []):
            if isinstance(entry, str) and entry.lower() == app:
                return "ignoré"
            if isinstance(entry, dict) and str(entry.get("app", "")).lower() == app:
                return "ignoré"

        window = self.config.get("coalesceSeconds", 6)
        now = time.monotonic()
        with self._lock:
            previous = self._recent.get(notification.key())
            self._recent[notification.key()] = now
        if previous is not None and now - previous < window:
            return "groupé"
        return "accepted"

    def _in_quiet_hours(self):
        window = self.config.get("quietHours")
        if not window:
            return False
        try:
            start, end = window["from"], window["to"]
            now = time.strftime("%H:%M")
        except (KeyError, TypeError):
            return False
        if start <= end:
            return start <= now < end
        return now >= start or now < end

    def resolve(self, notification):
        if notification.pattern:
            return notification.pattern
        app = notification.app.lower()
        best = None
        for rule in self.config.get("rules", []):
            if str(rule.get("app", "")).lower() != app:
                continue
            if best is None or rule.get("priority", 0) > best.get("priority", 0):
                best = rule
        if best:
            notification.priority = max(notification.priority, best.get("priority", 0))
            return best.get("pattern", self.config["defaultPattern"])
        return self.config.get("defaultPattern", "info")

    def pattern(self, name):
        patterns = self.config.get("patterns", {})
        return patterns.get(name) or patterns.get("info") or DEFAULTS["patterns"]["info"]

    def test(self, pattern_name):
        notification = Notification(priority=99, received=time.time(), source="test",
                                    app="Test", title=pattern_name, pattern=pattern_name)
        self._queue.put(notification)

    def recent(self, limit=40):
        with self._lock:
            return self._log[-limit:][::-1]

    def _record(self, notification, outcome):
        entry = {
            "at": time.time(),
            "source": notification.source,
            "app": notification.app,
            "title": notification.title[:80],
            "pattern": notification.pattern,
            "outcome": outcome,
        }
        with self._lock:
            self._log.append(entry)
            del self._log[:-200]

    def _worker(self):
        while not self._stop.is_set():
            notification = self._queue.get()
            if notification is None:
                return
            name = self.resolve(notification)
            notification.pattern = name
            try:
                self._play(self.pattern(name))
            except LinkError as exc:
                self._record(notification, f"échec : {exc}")
            else:
                self._record(notification, "joué")

    def budget(self, leds, colour, brightness):
        per_led = self.config.get("ledMilliamps", 55)
        base = self.config.get("baseMilliamps", 100)
        weight = sum(colour) / 765
        return base + leds * per_led * weight * brightness / 255

    def limit(self):
        configured = self.config.get("powerBudgetMa", 700)
        cached = self.bridge.cached() or {}
        module = ((cached.get("info") or {}).get("leds") or {}).get("maxpwr") or 0
        return min(configured, module) if module > 0 else configured

    def _fit_to_budget(self, leds, colour, brightness):
        limit = self.limit()
        while brightness > 5 and self.budget(leds, colour, brightness) > limit:
            brightness -= 5
        return brightness

    def _play(self, pattern):
        snapshot = self.bridge.snapshot(max_age=0).get("state") or {}
        baseline = replayable(snapshot)
        if not snapshot.get("on", True) and not self.config.get("notifyWhenOff", True):
            return

        segments = snapshot.get("seg") or [{}]
        main = snapshot.get("mainseg", 0)
        current = segments[main] if main < len(segments) else segments[0]
        total = current.get("stop", 144) - current.get("start", 0)

        colour = pattern.get("color", [255, 180, 60])
        span = pattern.get("leds") or total
        span = max(1, min(int(span), total))
        brightness = self._fit_to_budget(span, colour, int(pattern.get("bri", 130)))

        lit = {
            "on": True,
            "bri": brightness,
            "tt": 0,
            "seg": [{"id": main, "start": current.get("start", 0),
                     "stop": current.get("start", 0) + span,
                     "fx": 0, "sx": 128, "ix": 128, "pal": 0,
                     "col": [colour, [0, 0, 0], [0, 0, 0]]}],
        }
        dark = {"tt": 0, "bri": 0}

        self.playing = pattern
        if self.audio:
            self.audio.pause()
        try:
            for _ in range(max(1, int(pattern.get("flashes", 2)))):
                self.bridge.link.request(lit, expect_response=False)
                time.sleep(max(0.05, pattern.get("onMs", 240) / 1000))
                self.bridge.link.request(dark, expect_response=False)
                time.sleep(max(0.05, pattern.get("offMs", 160) / 1000))
        finally:
            self.playing = None
            self.bridge.apply(baseline)
            if self.audio:
                self.audio.resume()
