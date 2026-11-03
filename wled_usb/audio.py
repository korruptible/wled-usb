from __future__ import annotations

import json
import pathlib
import threading
import time

from .link import LinkError

MAGIC = b"\xa5\x5a"
MODES = ("spectrum", "bass", "wave", "pulse")
AGC_FLOOR = 0.04
AGC_RELEASE = 0.995
PIXEL_DECAY = 0.72
AGC_MIX = 0.35
ZONES = 6
AUTO_ATTACK = 0.3
AUTO_RELEASE = 0.01
AUTO_TARGET = 1.0
AUTO_ENV_FLOOR = 0.08
AUTO_MIN = 0.4
AUTO_MAX = 6.0
MAX_GAIN = 8.0


def adalight(pixels):
    last = len(pixels) // 3 - 1
    high, low = (last >> 8) & 0xFF, last & 0xFF
    return b"Ada" + bytes([high, low, high ^ low ^ 0x55]) + pixels


PALETTES = {
    "rainbow": [(255, 0, 0), (255, 190, 0), (0, 255, 40), (0, 180, 255), (120, 0, 255)],
    "ember": [(255, 30, 0), (255, 110, 0), (255, 190, 40), (255, 240, 170)],
    "ocean": [(0, 70, 210), (0, 150, 235), (0, 230, 220), (190, 255, 255)],
    "forest": [(25, 130, 25), (70, 205, 45), (155, 240, 65), (245, 255, 180)],
    "neon": [(255, 0, 120), (175, 0, 255), (0, 150, 255), (0, 255, 200)],
    "ice": [(45, 95, 225), (95, 165, 245), (175, 215, 255), (255, 255, 255)],
    "sunset": [(130, 0, 155), (235, 0, 100), (255, 110, 30), (255, 220, 120)],
}
DEFAULT_PALETTE = "rainbow"

LEGACY_NAMES = {
    "spectre": "spectrum", "graves": "bass", "onde": "wave", "pulsation": "pulse",
    "arc-en-ciel": "rainbow", "braise": "ember", "océan": "ocean", "forêt": "forest",
    "néon": "neon", "glace": "ice", "coucher": "sunset",
}


def shade(palette, position, value):
    if value <= 0:
        return 0, 0, 0
    stops = PALETTES.get(palette) or PALETTES[DEFAULT_PALETTE]
    place = max(0.0, min(1.0, position)) * (len(stops) - 1)
    low = int(place)
    blend = place - low
    start, end = stops[low], stops[min(low + 1, len(stops) - 1)]
    scale = min(1.0, value)
    return tuple(int((start[i] + (end[i] - start[i]) * blend) * scale) for i in range(3))


def centroid(levels):
    total = sum(levels)
    if total <= 0:
        return 0.0
    return sum(index * value for index, value in enumerate(levels)) / total / max(1, len(levels) - 1)


def spectrum(levels, count, gain, palette, state):
    span = len(levels) / ZONES
    groups = [max(levels[int(z * span):int((z + 1) * span)] or [0.0]) for z in range(ZONES)]
    half = count // 2
    zone = max(1, half // ZONES)
    out = [(0, 0, 0)] * count
    for index, energy in enumerate(groups):
        lit = int(round(zone * min(1.0, energy * gain)))
        tone = index / max(1, ZONES - 1)
        for step in range(lit):
            colour = shade(palette, tone, 1.0 - 0.45 * step / zone)
            position = index * zone + step
            if half - 1 - position >= 0:
                out[half - 1 - position] = colour
            if half + position < count:
                out[half + position] = colour
    return out


def bass(levels, count, gain, palette, state):
    energy = sum(levels[:6]) / 6
    treble = sum(levels[14:]) / max(1, len(levels) - 14)
    reach = int(count / 2 * min(1.0, energy * gain))
    middle = count // 2
    out = [(0, 0, 0)] * count
    for offset in range(reach + 1):
        fade = 1 - offset / max(1, count / 2)
        colour = shade(palette, 0.15 + 0.7 * treble + 0.15 * offset / max(1, count / 2), fade)
        if middle - offset >= 0:
            out[middle - offset] = colour
        if middle + offset < count:
            out[middle + offset] = colour
    return out


def wave(levels, count, gain, palette, state):
    trail = state.setdefault("trail", [0.0] * count)
    if len(trail) != count:
        trail = state["trail"] = [0.0] * count
    for index in range(count - 1, 0, -1):
        trail[index] = trail[index - 1] * 0.985
    punch = sum(levels[:5]) / 5
    previous = state.get("punch", 0.0)
    state["punch"] = punch
    trail[0] = min(1.0, max(punch * gain if punch > previous * 1.12 else 0.0, trail[0] * 0.5))
    tone = centroid(levels)
    return [shade(palette, tone * 0.5 + 0.5 * value, value) for value in trail]


def pulse(levels, count, gain, palette, state):
    energy = sum(levels) / len(levels)
    return [shade(palette, centroid(levels), energy * gain)] * count


RENDERERS = {"spectrum": spectrum, "bass": bass, "wave": wave, "pulse": pulse}

DRIVES = {
    "spectrum": lambda levels: max(levels, default=0.0),
    "bass": lambda levels: sum(levels[:6]) / 6,
    "wave": lambda levels: sum(levels[:5]) / 5,
    "pulse": lambda levels: sum(levels) / max(1, len(levels)),
}


class AudioEngine:
    def __init__(self, bridge, fps=25, mode="spectrum", gain=0.8, curve=0.55, floor=0.03,
                 palette=DEFAULT_PALETTE, auto=True, config_path=None):
        self.bridge = bridge
        self.fps = fps
        self.mode = LEGACY_NAMES.get(mode, mode)
        if self.mode not in RENDERERS:
            self.mode = "spectrum"
        self.gain = gain
        self.curve = curve
        self.floor = floor
        self.palette = LEGACY_NAMES.get(palette, palette)
        if self.palette not in PALETTES:
            self.palette = DEFAULT_PALETTE
        self.auto = bool(auto)
        self.path = pathlib.Path(config_path) if config_path else None
        self._restore()
        self.frames = 0
        self.dropped = 0
        self.last_error = ""
        self.level = 0.0
        self.raw = 0.0

        self._agc = []
        self._envelope = AUTO_ENV_FLOOR
        self._drive = self.gain
        self._presence = 0.0
        self._pixels = []
        self._state = {}
        self._paused = threading.Event()
        self._draw = threading.Lock()
        self._stop = threading.Event()
        self._sent_at = 0.0
        self._thread = None

    def status(self):
        return {
            "running": self._thread is not None and self._thread.is_alive(),
            "paused": self._paused.is_set(),
            "mode": self.mode,
            "fps": self.fps,
            "gain": round(self.gain, 2),
            "auto": self.auto,
            "drive": round(self._drive, 2),
            "curve": round(self.curve, 2),
            "floor": round(self.floor, 2),
            "frames": self.frames,
            "dropped": self.dropped,
            "level": round(self.level, 3),
            "raw": round(self.raw, 3),
            "error": self.last_error,
            "modes": list(MODES),
            "palette": self.palette,
            "palettes": list(PALETTES),
        }

    def configure(self, mode=None, gain=None, fps=None, curve=None, floor=None,
                  palette=None, auto=None):
        mode = LEGACY_NAMES.get(mode, mode)
        if mode in RENDERERS:
            self.mode = mode
        if gain is not None:
            self.gain = max(0.1, min(8.0, float(gain)))
        if fps is not None:
            self.fps = max(1, min(60, int(fps)))
        if curve is not None:
            self.curve = max(0.2, min(1.0, float(curve)))
        if floor is not None:
            self.floor = max(0.0, min(0.4, float(floor)))
        palette = LEGACY_NAMES.get(palette, palette)
        if palette in PALETTES:
            self.palette = palette
        if auto is not None:
            self.auto = bool(auto)
        self._remember()
        return self.status()

    def _restore(self):
        if self.path is None:
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if not isinstance(saved, dict):
            return
        mode = LEGACY_NAMES.get(saved.get("mode"), saved.get("mode"))
        mode = LEGACY_NAMES.get(mode, mode)
        if mode in RENDERERS:
            self.mode = mode
        palette = LEGACY_NAMES.get(saved.get("palette"), saved.get("palette"))
        palette = LEGACY_NAMES.get(palette, palette)
        if palette in PALETTES:
            self.palette = palette
        if isinstance(saved.get("auto"), bool):
            self.auto = saved["auto"]
        for name, low, high in (("gain", 0.1, 8.0), ("curve", 0.2, 1.0), ("floor", 0.0, 0.4)):
            if isinstance(saved.get(name), (int, float)):
                setattr(self, name, max(low, min(high, float(saved[name]))))
        if isinstance(saved.get("fps"), int):
            self.fps = max(1, min(60, saved["fps"]))

    def _remember(self):
        if self.path is None:
            return
        payload = {"mode": self.mode, "palette": self.palette, "gain": self.gain,
                   "curve": self.curve, "floor": self.floor, "fps": self.fps,
                   "auto": self.auto}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(payload, indent=1), encoding="utf-8")
        except OSError:
            pass

    def pause(self):
        self._paused.set()

    def resume(self):
        self._paused.clear()

    def live(self, within=2.0):
        return not self._paused.is_set() and time.monotonic() - self._sent_at < within

    def paint(self, pixels):
        frame = adalight(bytes(channel for pixel in pixels for channel in pixel))
        with self._draw:
            self._pixels = list(pixels)
            self.bridge.link.send_raw(frame)

    def start(self, stream):
        self._thread = threading.Thread(target=self._loop, args=(stream,),
                                        name="wled-audio", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()

    def led_count(self):
        cached = self.bridge.cached() or {}
        count = ((cached.get("info") or {}).get("leds") or {}).get("count")
        return int(count) if count else 0

    def _loop(self, stream):
        while not self._stop.is_set():
            bands = self._read_frame(stream)
            if bands is None:
                return
            self.level = sum(bands) / (len(bands) * 255)
            if self._paused.is_set():
                continue
            self._emit(bands)

    def _read_frame(self, stream):
        header = _read_exactly(stream, 4)
        if header is None:
            return None
        while header[:2] != MAGIC:
            nxt = _read_exactly(stream, 1)
            if nxt is None:
                return None
            header = header[1:] + nxt
        self.raw = header[3] / 255
        payload = _read_exactly(stream, header[2])
        return list(payload) if payload is not None else None

    def _normalise(self, bands):
        if len(self._agc) != len(bands):
            self._agc = [AGC_FLOOR] * len(bands)
        presence = min(1.0, max(0.0, (self.raw - 0.004) * 12))
        self._presence = presence
        levels = []
        for index, value in enumerate(bands):
            raw = value / 255
            ceiling = max(raw, self._agc[index] * AGC_RELEASE, AGC_FLOOR)
            self._agc[index] = ceiling
            relative = min(1.0, raw / ceiling)
            shaped = (relative * (1 - AGC_MIX) + raw * AGC_MIX) ** self.curve
            levels.append(shaped * presence)
        return levels

    def _drive_for(self, levels):
        if not self.auto:
            return self.gain
        reach = DRIVES[self.mode](levels)
        if self._presence > 0:
            rate = AUTO_ATTACK if reach > self._envelope else AUTO_RELEASE
            self._envelope += (reach - self._envelope) * rate
        ceiling = max(self._envelope, AUTO_ENV_FLOOR)
        lift = max(AUTO_MIN, min(AUTO_MAX, AUTO_TARGET / ceiling))
        return min(MAX_GAIN, self.gain * lift)

    def _render(self, bands, count):
        levels = self._normalise(bands)
        self._drive = self._drive_for(levels)
        fresh = RENDERERS[self.mode](levels, count, self._drive, self.palette, self._state)
        if self.floor > 0 and self._presence > 0:
            glow = shade(self.palette, centroid(levels), self.floor * self._presence)
            fresh = [pixel if pixel != (0, 0, 0) else glow for pixel in fresh]
        if len(self._pixels) != count:
            self._pixels = [(0, 0, 0)] * count
        out = bytearray()
        for index, (red, green, blue) in enumerate(fresh):
            old = self._pixels[index]
            kept = tuple(max(channel, int(previous * PIXEL_DECAY))
                         for channel, previous in zip((red, green, blue), old))
            self._pixels[index] = kept
            out += bytes(kept)
        return bytes(out)

    def _emit(self, bands):
        now = time.monotonic()
        if now - self._sent_at < 1.0 / self.fps:
            self.dropped += 1
            return
        count = self.led_count()
        if not count:
            return
        pixels = self._render(bands, count)
        with self._draw:
            if self._paused.is_set():
                return
            try:
                self.bridge.link.send_raw(adalight(pixels))
            except LinkError as exc:
                self.last_error = str(exc)
                return
        self.last_error = ""
        self._sent_at = now
        self.frames += 1


def _read_exactly(stream, size):
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            return None
        chunks += chunk
    return bytes(chunks)
