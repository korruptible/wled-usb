from __future__ import annotations

import json
import os
import pathlib

LANGUAGES = ("en", "fr")
DEFAULT_LANGUAGE = "en"


def from_locale(tag=None):
    if not tag:
        tag = os.environ.get("LC_ALL") or os.environ.get("LANG") or ""
    tag = tag.replace("_", "-").split(".")[0].lower()
    primary = tag.split("-")[0]
    return primary if primary in LANGUAGES else DEFAULT_LANGUAGE


class UiSettings:
    def __init__(self, path=None, language=None):
        self.path = pathlib.Path(path) if path else None
        self.language = from_locale(language)
        self._restore()

    def status(self):
        return {"language": self.language, "languages": list(LANGUAGES)}

    def configure(self, language=None):
        if language in LANGUAGES:
            self.language = language
            self._remember()
        return self.status()

    def _restore(self):
        if self.path is None:
            return
        try:
            saved = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return
        if isinstance(saved, dict) and saved.get("language") in LANGUAGES:
            self.language = saved["language"]

    def _remember(self):
        if self.path is None:
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"language": self.language}, indent=1),
                                 encoding="utf-8")
        except OSError:
            pass
