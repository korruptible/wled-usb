from __future__ import annotations

import json
import pathlib
import threading

SEGMENT_KEYS = (
    "id", "start", "stop", "grp", "spc", "of", "on", "frz", "bri", "cct",
    "set", "col", "fx", "sx", "ix", "pal", "c1", "c2", "c3", "sel", "rev",
    "mi", "o1", "o2", "o3", "si", "m12",
)
STATE_KEYS = ("on", "bri", "transition", "mainseg")


class PresetStore:
    def __init__(self, path):
        self.path = pathlib.Path(path)
        self._lock = threading.Lock()
        self._data = self._load()

    def _load(self):
        try:
            parsed = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"0": {}}
        if not isinstance(parsed, dict):
            return {"0": {}}
        parsed.setdefault("0", {})
        return parsed

    def _flush(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=1), encoding="utf-8")
        tmp.replace(self.path)

    def as_dict(self):
        with self._lock:
            return dict(self._data)

    def known_name(self, slot):
        with self._lock:
            entry = self._data.get(str(slot))
        return entry.get("n") if isinstance(entry, dict) else None

    def remember(self, slot, state, name=None):
        slot = str(int(slot))
        if slot == "0":
            return
        entry = snapshot(state)
        with self._lock:
            previous = self._data.get(slot)
            if name:
                entry["n"] = name
            elif isinstance(previous, dict) and previous.get("n"):
                entry["n"] = previous["n"]
            else:
                entry["n"] = f"Preset {slot}"
            self._data[slot] = entry
            self._flush()

    def forget(self, slot):
        with self._lock:
            if self._data.pop(str(int(slot)), None) is not None:
                self._flush()

    def rename(self, slot, name):
        slot = str(int(slot))
        with self._lock:
            entry = self._data.get(slot)
            if isinstance(entry, dict):
                entry["n"] = name
                self._flush()


def snapshot(state):
    if not isinstance(state, dict):
        return {}
    entry = {key: state[key] for key in STATE_KEYS if key in state}
    segments = state.get("seg")
    if isinstance(segments, list):
        entry["seg"] = [
            {key: seg[key] for key in SEGMENT_KEYS if key in seg}
            for seg in segments
            if isinstance(seg, dict)
        ]
    return entry
