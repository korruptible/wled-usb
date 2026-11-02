from __future__ import annotations

import contextlib
import json
import queue
import threading
import time

from .serialport import RawSerial

TPM2_START = 0xC9
TPM2_DATA = 0xDA
MAX_LINE = 65536


class LinkError(RuntimeError):
    pass


class WledLink:
    def __init__(self, port, baudrate=115200, on_state=None):
        self.port = port
        self.baudrate = baudrate
        self.connected = False
        self.last_error = None

        self._on_state = on_state
        self._serial = None
        self._buf = bytearray()
        self._events = queue.Queue()
        self._io = threading.RLock()
        self._stop = threading.Event()
        self._suspend = threading.Event()
        self._idle = threading.Event()
        self._ready = threading.Event()
        self._thread = None

    def start(self):
        self._thread = threading.Thread(target=self._loop, name="wled-link", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=3)
        self._close()

    @contextlib.contextmanager
    def suspended(self):
        with self._io:
            self._suspend.set()
            if not self._idle.wait(timeout=5):
                raise LinkError("the serial reader did not release the port")
            try:
                yield
            finally:
                self._suspend.clear()
                self._idle.clear()

    def request(self, payload, timeout=4.0, expect_response=True):
        body = dict(payload)
        if expect_response:
            body["v"] = True
        encoded = json.dumps(body, separators=(",", ":")).encode() + b"\n"
        with self._io:
            self._drain()
            self._write(encoded)
            if not expect_response:
                return None
            return self._wait("json", timeout)

    def send_raw(self, payload):
        with self._io:
            self._write(payload)

    def read_pixels(self, timeout=2.0):
        with self._io:
            self._drain()
            self._write(b"L")
            return self._wait("pixels", timeout)

    def firmware_version(self, timeout=2.0):
        with self._io:
            self._drain()
            self._write(b"v")
            return self._wait("line", timeout)

    def _loop(self):
        while not self._stop.is_set():
            if self._suspend.is_set():
                self._close()
                self._idle.set()
                time.sleep(0.1)
                continue

            if self._serial is None and not self._open():
                time.sleep(2.0)
                continue

            try:
                chunk = self._serial.read(0.1)
            except Exception as exc:
                self._fail(exc)
                continue

            if chunk:
                self._feed(chunk)

    def _open(self):
        try:
            handle = RawSerial(self.port, self.baudrate)
        except Exception as exc:
            self.last_error = exc
            self.connected = False
            return False

        self._serial = handle
        self._buf.clear()
        self.connected = True
        self.last_error = None
        self._ready.set()
        return True

    def _fail(self, exc):
        self.last_error = exc
        self.connected = False
        self._close()
        time.sleep(1.0)

    def _close(self):
        if self._serial is not None:
            try:
                self._serial.close()
            except Exception:
                pass
        self._serial = None
        self.connected = False
        self._ready.clear()

    def wait_ready(self, timeout=2.0):
        return self._ready.wait(timeout)

    def _write(self, raw):
        if not self.connected and not self._suspend.is_set():
            self.wait_ready()
        if self._serial is None or not self.connected:
            raise LinkError(f"serial port unavailable ({self.last_error or 'not connected'})")
        try:
            self._serial.write(raw)
        except Exception as exc:
            self._fail(exc)
            raise LinkError(f"serial write failed: {exc}") from exc

    def _drain(self):
        if self._serial is not None:
            self._serial.flush_input()
        self._buf.clear()
        while True:
            try:
                self._events.get_nowait()
            except queue.Empty:
                return

    def _wait(self, kind, timeout):
        deadline = time.monotonic() + timeout
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LinkError(f"no answer from the module ({kind})")
            try:
                got_kind, payload = self._events.get(timeout=remaining)
            except queue.Empty:
                raise LinkError(f"no answer from the module ({kind})") from None
            if got_kind == kind:
                return payload

    def _feed(self, chunk):
        buf = self._buf
        buf.extend(chunk)
        while buf:
            if buf[0] == TPM2_START:
                if len(buf) < 4:
                    return
                if buf[1] != TPM2_DATA:
                    del buf[0]
                    continue
                length = (buf[2] << 8) | buf[3]
                frame = 4 + length + 1
                if len(buf) < frame:
                    return
                payload = bytes(buf[4 : 4 + length])
                del buf[:frame]
                if buf[:1] == b"\n":
                    del buf[0]
                self._events.put(("pixels", payload))
                continue

            end = buf.find(b"\n")
            if end < 0:
                if len(buf) > MAX_LINE:
                    del buf[:-MAX_LINE]
                return
            line = bytes(buf[:end]).strip()
            del buf[: end + 1]
            if line:
                self._dispatch_line(line)

    def _dispatch_line(self, line):
        if line[:1] in (b"{", b"["):
            try:
                parsed = json.loads(line.decode("utf-8", "replace"))
            except ValueError:
                pass
            else:
                self._events.put(("json", parsed))
                if self._on_state and isinstance(parsed, dict) and "state" in parsed:
                    self._on_state(parsed)
                return
        self._events.put(("line", line.decode("utf-8", "replace")))
