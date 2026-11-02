from __future__ import annotations

import pathlib
import subprocess
import sys
import threading
import time

ESP_IMAGE_MAGIC = 0xE9
APP_OFFSET = 0x10000


class FlashError(RuntimeError):
    pass


class Flasher:
    def __init__(self, link, chip="esp32", python_exe=None):
        self.link = link
        self.chip = chip
        self.python_exe = python_exe or sys.executable
        self._lock = threading.Lock()
        self._log = []
        self._running = False
        self._outcome = None
        self._started_at = None

    def status(self, since=0):
        with self._lock:
            since = max(0, min(int(since), len(self._log)))
            return {
                "running": self._running,
                "outcome": self._outcome,
                "startedAt": self._started_at,
                "next": len(self._log),
                "lines": self._log[since:],
            }

    def start(self, firmware, offset=APP_OFFSET, baud=460800, erase=False):
        path = pathlib.Path(firmware)
        if not path.is_file():
            raise FlashError(f"fichier introuvable : {path}")
        if path.stat().st_size < 1024:
            raise FlashError("le fichier est trop petit pour un firmware")
        with path.open("rb") as handle:
            if handle.read(1)[:1] != bytes([ESP_IMAGE_MAGIC]):
                raise FlashError(
                    "ce fichier ne commence pas par la signature ESP (0xE9) : "
                    "ce n'est pas une image firmware valide"
                )

        self._begin()
        command = self._esptool(baud) + ["write-flash"]
        if erase:
            command.append("--erase-all")
        command += [hex(int(offset)), str(path)]
        self._spawn(command)

    def _append(self, text):
        with self._lock:
            self._log.append(text)

    def probe(self, baud=115200):
        self._begin()
        self._spawn(self._esptool(baud) + ["flash-id"])

    def _esptool(self, baud):
        return [
            self.python_exe, "-m", "esptool",
            "--chip", self.chip,
            "--port", self.link.port,
            "--baud", str(int(baud)),
            "--before", "default-reset",
            "--after", "hard-reset",
        ]

    def _begin(self):
        with self._lock:
            if self._running:
                raise FlashError("an esptool operation is already running")
            self._running = True
            self._outcome = None
            self._started_at = time.time()
            self._log = []

    def _spawn(self, command):
        threading.Thread(target=self._run, args=(command,), name="wled-esptool",
                         daemon=True).start()

    def _run(self, command):
        self._append(f"$ {' '.join(command)}")
        outcome = "error"
        try:
            with self.link.suspended():
                self._append(f"port {self.link.port} released, starting esptool…")
                code = self._stream(command)
                outcome = "ok" if code == 0 else "error"
                self._append(f"esptool finished with code {code}")
        except Exception as exc:
            self._append(f"failed: {exc}")
        finally:
            with self._lock:
                self._running = False
                self._outcome = outcome
            self._append("serial port taken back by the bridge")

    def _stream(self, command):
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            bufsize=0,
        )
        pending = bytearray()
        while True:
            chunk = process.stdout.read(1)
            if not chunk:
                break
            if chunk in (b"\n", b"\r"):
                if pending:
                    self._append(pending.decode("utf-8", "replace").rstrip())
                    pending.clear()
            else:
                pending += chunk
        if pending:
            self._append(pending.decode("utf-8", "replace").rstrip())
        return process.wait()
