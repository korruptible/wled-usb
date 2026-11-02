from __future__ import annotations

import base64
import hashlib
import struct
import threading

HANDSHAKE_GUID = b"258EAFA5-E914-47DA-95CA-C5AB0DC85B11"

OP_CONTINUATION = 0x0
OP_TEXT = 0x1
OP_BINARY = 0x2
OP_CLOSE = 0x8
OP_PING = 0x9
OP_PONG = 0xA

MAX_PAYLOAD = 1 << 20


def accept_key(client_key):
    digest = hashlib.sha1(client_key.encode("ascii") + HANDSHAKE_GUID).digest()
    return base64.b64encode(digest).decode("ascii")


def encode_frame(opcode, payload):
    header = bytearray([0x80 | opcode])
    size = len(payload)
    if size < 126:
        header.append(size)
    elif size < 1 << 16:
        header.append(126)
        header += struct.pack("!H", size)
    else:
        header.append(127)
        header += struct.pack("!Q", size)
    return bytes(header) + payload


class WsConnection:
    def __init__(self, rfile, wfile):
        self._rfile = rfile
        self._wfile = wfile
        self._send_lock = threading.Lock()
        self.closed = False
        self.live = False

    def send_text(self, text):
        self._send(OP_TEXT, text.encode("utf-8"))

    def send_binary(self, payload):
        self._send(OP_BINARY, payload)

    def _send(self, opcode, payload):
        if self.closed:
            return
        with self._send_lock:
            try:
                self._wfile.write(encode_frame(opcode, payload))
                self._wfile.flush()
            except Exception:
                self.closed = True

    def close(self):
        if not self.closed:
            self._send(OP_CLOSE, b"")
            self.closed = True

    def read_message(self):
        buffer = bytearray()
        message_op = None
        while True:
            frame = self._read_frame()
            if frame is None:
                return None
            fin, opcode, payload = frame

            if opcode == OP_CLOSE:
                self.closed = True
                return None
            if opcode == OP_PING:
                self._send(OP_PONG, payload)
                continue
            if opcode == OP_PONG:
                continue

            if opcode != OP_CONTINUATION:
                message_op = opcode
                buffer = bytearray(payload)
            else:
                buffer += payload

            if fin:
                return message_op, bytes(buffer)

    def _read_frame(self):
        head = self._recv(2)
        if head is None:
            return None
        fin = bool(head[0] & 0x80)
        opcode = head[0] & 0x0F
        masked = bool(head[1] & 0x80)
        size = head[1] & 0x7F

        if size == 126:
            extended = self._recv(2)
            if extended is None:
                return None
            size = struct.unpack("!H", extended)[0]
        elif size == 127:
            extended = self._recv(8)
            if extended is None:
                return None
            size = struct.unpack("!Q", extended)[0]

        if size > MAX_PAYLOAD:
            self.closed = True
            return None

        mask = self._recv(4) if masked else None
        if masked and mask is None:
            return None

        payload = self._recv(size) if size else b""
        if payload is None:
            return None
        if masked:
            payload = bytes(byte ^ mask[index % 4] for index, byte in enumerate(payload))
        return fin, opcode, payload

    def _recv(self, count):
        chunks = bytearray()
        while len(chunks) < count:
            try:
                chunk = self._rfile.read(count - len(chunks))
            except Exception:
                self.closed = True
                return None
            if not chunk:
                self.closed = True
                return None
            chunks += chunk
        return bytes(chunks)
