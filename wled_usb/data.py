from __future__ import annotations

import json
import pathlib

_PATH = pathlib.Path(__file__).resolve().parent.parent / "data" / "wled-data.json"


class StaticData:
    def __init__(self, path=_PATH):
        try:
            raw = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        except OSError as exc:
            raise SystemExit(
                f"effect database unreadable at {path}: {exc}\n"
                "regenerate it with: python tools/gen-data.py v16.0.1"
            ) from exc
        self.version = raw["version"]
        self.effects = raw["effects"]
        self.fxdata = raw["fxdata"]
        self.palettes = raw["palettes"]
        self.per_page = raw["palxItemsPerPage"]
        self._palx = raw["palx"]
        self.max_page = max(0, (len(self.palettes) - 1) // self.per_page)

    def palx_page(self, page):
        page = max(0, min(int(page), self.max_page))
        start = page * self.per_page
        end = min(start + self.per_page, len(self.palettes))
        return {
            "m": self.max_page,
            "p": {str(i): self._palx[str(i)] for i in range(start, end)},
        }

    def matches(self, info):
        if not isinstance(info, dict):
            return True, ""
        problems = []
        fxcount, palcount = info.get("fxcount"), info.get("palcount")
        version = info.get("ver")
        if fxcount is not None and fxcount != len(self.effects):
            problems.append(f"{fxcount} effets sur le module contre {len(self.effects)} en base")
        if palcount is not None and palcount != len(self.palettes):
            problems.append(f"{palcount} palettes sur le module contre {len(self.palettes)} en base")
        if version and version != self.version:
            problems.append(f"firmware {version} contre base {self.version}")
        return not problems, " ; ".join(problems)
