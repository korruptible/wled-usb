from __future__ import annotations

import json
import pathlib
import socket
import time
import tempfile
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from .bridge import replayable
from .flash import APP_OFFSET, FlashError
from .link import LinkError
from .notify import Notification
from .ws import OP_TEXT, WsConnection, accept_key

ROOT = pathlib.Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
PUBLIC = ROOT / "public"

HTML = "text/html; charset=utf-8"
JS = "application/javascript; charset=utf-8"
CSS = "text/css; charset=utf-8"

STATIC = {
    "/": (VENDOR / "index.htm", HTML),
    "/index.htm": (VENDOR / "index.htm", HTML),
    "/index.css": (VENDOR / "index.css", CSS),
    "/index.js": (VENDOR / "index.js", JS),
    "/iro.js": (VENDOR / "iro.js", JS),
    "/rangetouch.js": (VENDOR / "rangetouch.js", JS),
    "/liveview": (VENDOR / "liveview.htm", HTML),
    "/liveview.htm": (VENDOR / "liveview.htm", HTML),
    "/bridge": (PUBLIC / "bridge.html", HTML),
    "/skin.css": (PUBLIC / "skin.css", CSS),
}

UNAVAILABLE_PREFIXES = ("/settings", "/edit", "/update", "/dmxmap", "/usermod")
MAX_FIRMWARE = 8 << 20
MAX_BODY = 1 << 20


def known_hosts(addresses, port):
    names = {"localhost", *addresses}
    return {f"[{name}]:{port}" if ":" in name else f"{name}:{port}" for name in names}


def _lenient_json(raw):
    text = raw.decode("utf-8", "replace").strip()
    try:
        return json.loads(text)
    except ValueError:
        return json.loads(text.replace("'", '"'))


class BridgeServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, bridge, flasher, notifier=None, sources=None, audio=None,
                 hosts=None):
        self.address_family = socket.AF_INET6 if ":" in address[0] else socket.AF_INET
        self.hosts = hosts or known_hosts([address[0]], address[1])
        self.origins = {f"http://{host}" for host in self.hosts}
        self.audio = audio
        self.bridge = bridge
        self.flasher = flasher
        self.notifier = notifier
        self.sources = sources or {}
        super().__init__(address, BridgeHandler)


class BridgeHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "wled-usb-bridge"

    def log_message(self, fmt, *args):
        pass

    @property
    def bridge(self):
        return self.server.bridge

    @property
    def flasher(self):
        return self.server.flasher

    @property
    def notifier(self):
        return self.server.notifier

    def do_GET(self):
        if not self._trusted():
            return
        path, query = self._split()
        if path == "/ws":
            self._handle_ws()
            return
        try:
            self._route_get(path, query)
        except LinkError as exc:
            self._json({"error": str(exc)}, 503)
        except ValueError as exc:
            self._json({"error": f"paramètre invalide : {exc}"}, 400)

    def do_POST(self):
        if not self._trusted():
            return
        path, query = self._split()
        try:
            self._route_post(path, query)
        except LinkError as exc:
            self._json({"error": str(exc)}, 503)
        except FlashError as exc:
            self._json({"error": str(exc)}, 400)
        except ValueError as exc:
            self._json({"error": f"paramètre invalide : {exc}"}, 400)

    def _trusted(self):
        host = (self.headers.get("Host") or "").lower()
        if host not in self.server.hosts:
            self._json({"error": "en-tête Host inattendu"}, 421)
            return False
        origin = (self.headers.get("Origin") or "").lower()
        if origin and origin not in self.server.origins:
            self._json({"error": "origine tierce refusée"}, 403)
            return False
        return True

    def _split(self):
        parsed = urllib.parse.urlsplit(self.path)
        return parsed.path.rstrip("/") or "/", urllib.parse.parse_qs(parsed.query)

    def _route_get(self, path, query):
        data = self.bridge.data

        if path in STATIC:
            self._file(*STATIC[path])
            return
        if path.startswith(UNAVAILABLE_PREFIXES):
            self._file(PUBLIC / "unavailable.html", HTML, status=200)
            return

        if path == "/json":
            snapshot = self.bridge.snapshot()
            self._json({**snapshot, "effects": data.effects, "palettes": data.palettes})
        elif path == "/json/si":
            self._json(self.bridge.snapshot())
        elif path == "/json/state":
            self._json(self.bridge.snapshot().get("state", {}))
        elif path == "/json/info":
            self._json(self.bridge.snapshot().get("info", {}))
        elif path == "/json/effects":
            self._json(data.effects)
        elif path == "/json/palettes":
            self._json(data.palettes)
        elif path == "/json/fxdata":
            self._json(data.fxdata)
        elif path == "/json/palx":
            self._json(data.palx_page(query.get("page", ["0"])[0]))
        elif path == "/json/nodes":
            self._json({"nodes": []})
        elif path == "/json/live":
            self._json({"leds": self.bridge.live_leds()})
        elif path == "/presets.json":
            self._json(self.bridge.presets.as_dict())
        elif path == "/bridge/status":
            self._json(self._status())
        elif path == "/bridge/flash/status":
            since = int(query.get("since", ["0"])[0])
            self._json(self.flasher.status(since))
        elif path == "/bridge/audio":
            self._json(self.server.audio.status() if self.server.audio
                       else {"running": False})
        elif path == "/bridge/notify":
            self._json(self._notify_status())
        else:
            self._json({"error": "endpoint indisponible via le pont USB"}, 404)

    def _route_post(self, path, query):
        if path in ("/json", "/json/state", "/json/si"):
            payload = _lenient_json(self._body())
            if not isinstance(payload, dict):
                self._json({"error": "objet JSON attendu"}, 400)
                return
            self._json(self.bridge.apply(payload))
        elif path == "/bridge/flash":
            self._start_flash(query)
        elif path == "/bridge/flash/probe":
            self.flasher.probe()
            self._json({"started": True})
        elif path == "/bridge/notify":
            payload = _lenient_json(self._body())
            self._json({"outcome": self._fire(payload)})
        elif path == "/bridge/notify/test":
            self.notifier.test(query.get("pattern", ["info"])[0])
            self._json({"started": True})
        elif path == "/bridge/audio":
            payload = _lenient_json(self._body()) or {}
            self._json(self.server.audio.configure(
                mode=payload.get("mode"), gain=payload.get("gain"),
                fps=payload.get("fps"), curve=payload.get("curve"),
                floor=payload.get("floor"), palette=payload.get("palette"),
                auto=payload.get("auto")))
        elif path == "/bridge/notify/config":
            payload = _lenient_json(self._body())
            if not isinstance(payload, dict):
                self._json({"error": "objet JSON attendu"}, 400)
                return
            self._json(self.notifier.save(payload))
        elif path == "/bridge/presets/scan":
            self._json(self._scan_presets(query))
        elif path == "/bridge/presets/name":
            payload = _lenient_json(self._body())
            self.bridge.presets.rename(query["slot"][0], payload.get("n", ""))
            self._json(self.bridge.presets.as_dict())
        elif path == "/bridge/presets/forget":
            self.bridge.presets.forget(query["slot"][0])
            self._json(self.bridge.presets.as_dict())
        else:
            self._json({"error": "endpoint indisponible via le pont USB"}, 404)

    def _status(self):
        link = self.bridge.link
        cached = self.bridge.cached() or {}
        info = cached.get("info") or {}
        return {
            "port": link.port,
            "baudrate": link.baudrate,
            "connected": link.connected,
            "error": str(link.last_error) if link.last_error else None,
            "wsClients": self.bridge.client_count(),
            "dataVersion": self.bridge.data.version,
            "dataMismatch": self.bridge.mismatch,
            "device": {
                "name": info.get("name"),
                "version": info.get("ver"),
                "arch": info.get("arch"),
                "ledCount": (info.get("leds") or {}).get("count"),
                "fps": (info.get("leds") or {}).get("fps"),
                "uptime": info.get("uptime"),
                "freeHeap": info.get("freeheap"),
            },
            "flash": self.flasher.status(),
        }

    def _notify_status(self):
        return {
            "config": self.notifier.config,
            "recent": self.notifier.recent(),
            "playing": self.notifier.playing is not None,
            "sources": {name: source.status() for name, source in self.server.sources.items()},
        }

    def _fire(self, payload):
        if not isinstance(payload, dict):
            return "objet JSON attendu"
        return self.notifier.submit(Notification(
            priority=int(payload.get("priority", 0)),
            received=time.time(),
            source=str(payload.get("source", "http")),
            app=str(payload.get("app", "")),
            title=str(payload.get("title", "")),
            pattern=str(payload.get("pattern", "")),
        ))

    def _scan_presets(self, query):
        first = max(1, int(query.get("from", ["1"])[0]))
        last = min(int(query.get("to", ["25"])[0]), 250)
        restore = (self.bridge.snapshot(max_age=0).get("state") or {})
        found = []
        for slot in range(first, last + 1):
            try:
                result = self.bridge.apply({"ps": slot})
            except LinkError:
                break
            if (result.get("state") or {}).get("ps") == slot:
                found.append(slot)
        self.bridge.apply(replayable(restore))
        return {"found": found, "presets": self.bridge.presets.as_dict()}

    def _start_flash(self, query):
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            raise FlashError("corps de requête vide : envoyez le .bin en binaire")
        if length > MAX_FIRMWARE:
            raise FlashError(f"firmware trop volumineux ({length} octets)")

        offset = query.get("offset", [hex(APP_OFFSET)])[0]
        offset = int(offset, 16) if offset.lower().startswith("0x") else int(offset)
        baud = int(query.get("baud", ["460800"])[0])
        erase = query.get("erase", ["0"])[0] in ("1", "true", "yes")

        with tempfile.NamedTemporaryFile(prefix="wled-fw-", suffix=".bin", delete=False) as handle:
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                handle.write(chunk)
                remaining -= len(chunk)
            target = handle.name

        self.flasher.start(target, offset=offset, baud=baud, erase=erase)
        self._json({"started": True, "offset": hex(offset), "baud": baud, "bytes": length})

    def _handle_ws(self):
        key = self.headers.get("Sec-WebSocket-Key")
        upgrade = (self.headers.get("Upgrade") or "").lower()
        if not key or "websocket" not in upgrade:
            self._json({"error": "handshake websocket attendu"}, 400)
            return

        self.close_connection = True
        self.wfile.write(
            b"HTTP/1.1 101 Switching Protocols\r\n"
            b"Upgrade: websocket\r\n"
            b"Connection: Upgrade\r\n"
            b"Sec-WebSocket-Accept: " + accept_key(key).encode("ascii") + b"\r\n\r\n"
        )
        self.wfile.flush()
        self.connection.settimeout(None)

        connection = WsConnection(self.rfile, self.wfile)
        self.bridge.add_client(connection)
        try:
            cached = self.bridge.cached()
            if cached:
                connection.send_text(json.dumps(cached, separators=(",", ":")))
            while not connection.closed:
                message = connection.read_message()
                if message is None:
                    break
                opcode, payload = message
                if opcode == OP_TEXT:
                    self._ws_command(connection, payload)
        except Exception:
            pass
        finally:
            self.bridge.remove_client(connection)
            connection.close()

    def _ws_command(self, connection, payload):
        try:
            request = _lenient_json(payload)
        except ValueError:
            return
        if not isinstance(request, dict):
            return
        if "lv" in request:
            connection.live = bool(request.pop("lv"))
        try:
            result = self.bridge.apply(request) if request else self.bridge.snapshot()
        except LinkError:
            return
        connection.send_text(json.dumps(result, separators=(",", ":")))

    def _body(self):
        length = int(self.headers.get("Content-Length") or 0)
        if length > MAX_BODY:
            raise ValueError(f"corps trop volumineux ({length} octets)")
        return self.rfile.read(length) if length else b"{}"

    def _json(self, payload, status=200):
        self._respond(json.dumps(payload, separators=(",", ":")).encode("utf-8"),
                      "application/json; charset=utf-8", status)

    def _file(self, path, content_type, status=200):
        try:
            body = pathlib.Path(path).read_bytes()
        except OSError:
            self._json({"error": f"fichier manquant : {path.name}"}, 404)
            return
        self._respond(body, content_type, status)

    def _respond(self, body, content_type, status):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)
