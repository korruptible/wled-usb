from __future__ import annotations

import json
import threading
import time

from .link import LinkError


def replayable(state):
    return {key: value for key, value in state.items() if key not in ("ps", "pl")}


class Bridge:
    def __init__(self, link, data, presets, poll_interval=2.0, max_age=0.7, live_fps=12):
        self.link = link
        self.data = data
        self.presets = presets
        self.poll_interval = poll_interval
        self.max_age = max_age
        self.live_period = 1.0 / live_fps

        self.mismatch = ""
        self._cache = None
        self._fetched_at = 0.0
        self._cache_lock = threading.Lock()
        self._clients = set()
        self._clients_lock = threading.Lock()
        self._frame = None
        self._frame_at = 0.0
        self._frame_lock = threading.Lock()
        self._stop = threading.Event()

    def start(self):
        for target, name in ((self._poll_loop, "wled-poll"), (self._live_loop, "wled-live")):
            threading.Thread(target=target, name=name, daemon=True).start()

    def stop(self):
        self._stop.set()

    def snapshot(self, max_age=None):
        limit = self.max_age if max_age is None else max_age
        with self._cache_lock:
            fresh = self._cache is not None and (time.monotonic() - self._fetched_at) <= limit
            if fresh:
                return self._cache
        return self.apply({})

    def cached(self):
        with self._cache_lock:
            return self._cache

    def apply(self, payload):
        request = dict(payload)
        save_slot = request.get("psave")
        save_name = request.get("n")
        delete_slot = request.get("pdel")

        result = self.link.request(request)
        if not isinstance(result, dict) or "state" not in result:
            raise LinkError("unexpected answer from the module")

        self._store(result)

        state = result.get("state") or {}
        if save_slot is not None:
            self.presets.remember(save_slot, state, save_name)
        elif delete_slot is not None:
            self.presets.forget(delete_slot)
        else:
            slot = state.get("ps")
            if isinstance(slot, int) and slot > 0 and self.presets.known_name(slot) is None:
                self.presets.remember(slot, state)

        return result

    def live_frame(self, max_age=None):
        limit = self.live_period if max_age is None else max_age
        with self._frame_lock:
            if self._frame is not None and (time.monotonic() - self._frame_at) <= limit:
                return self._frame
        payload = self.link.read_pixels()
        with self._frame_lock:
            self._frame = payload
            self._frame_at = time.monotonic()
        return payload

    def live_leds(self):
        payload = self.live_frame()
        return [f"{payload[i]:02X}{payload[i + 1]:02X}{payload[i + 2]:02X}"
                for i in range(0, len(payload) - 2, 3)]

    def add_client(self, connection):
        with self._clients_lock:
            self._clients.add(connection)

    def remove_client(self, connection):
        with self._clients_lock:
            self._clients.discard(connection)

    def client_count(self):
        with self._clients_lock:
            return len(self._clients)

    def _clients_snapshot(self):
        with self._clients_lock:
            return list(self._clients)

    def _store(self, result):
        info = result.get("info")
        if info and not self.mismatch:
            ok, detail = self.data.matches(info)
            if not ok:
                self.mismatch = detail
        with self._cache_lock:
            changed = self._cache is None or self._cache.get("state") != result.get("state")
            self._cache = result
            self._fetched_at = time.monotonic()
        if changed:
            self._broadcast_state(result)

    def _broadcast_state(self, result):
        clients = self._clients_snapshot()
        if not clients:
            return
        message = json.dumps(result, separators=(",", ":"))
        for connection in clients:
            if connection.closed:
                self.remove_client(connection)
            else:
                connection.send_text(message)

    def _poll_loop(self):
        while not self._stop.wait(self.poll_interval):
            if not self.link.connected:
                continue
            try:
                self.apply({})
            except LinkError:
                pass

    def _live_loop(self):
        while not self._stop.wait(self.live_period):
            watchers = [c for c in self._clients_snapshot() if c.live and not c.closed]
            if not watchers or not self.link.connected:
                continue
            try:
                payload = self.live_frame()
            except LinkError:
                continue
            frame = b"L\x01" + payload
            for connection in watchers:
                connection.send_binary(frame)
