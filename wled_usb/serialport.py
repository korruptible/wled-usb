from __future__ import annotations

import errno
import fcntl
import os
import select
import termios


class SerialError(OSError):
    pass


class RawSerial:
    def __init__(self, path, baudrate):
        self.path = path
        self.baudrate = baudrate
        try:
            self.fd = os.open(path, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        except OSError as exc:
            if exc.errno == errno.EBUSY:
                raise SerialError(
                    f"{path} is already open in another program "
                    "(another bridge, a serial monitor or LedFx)"
                ) from exc
            raise
        try:
            self._claim()
            self._configure(baudrate)
        except Exception:
            os.close(self.fd)
            raise

    def _claim(self):
        try:
            fcntl.flock(self.fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise SerialError(
                f"{self.path} is already in use by another program "
                "(another bridge, a serial monitor or LedFx)"
            ) from exc
        try:
            fcntl.ioctl(self.fd, termios.TIOCEXCL)
        except OSError:
            pass

    def _configure(self, baudrate):
        speed = getattr(termios, f"B{baudrate}", baudrate)
        control = termios.CREAD | termios.CLOCAL | termios.CS8
        cc = list(termios.tcgetattr(self.fd)[6])
        cc[termios.VMIN] = 0
        cc[termios.VTIME] = 0
        termios.tcsetattr(self.fd, termios.TCSANOW, [0, 0, control, 0, speed, speed, cc])
        termios.tcflush(self.fd, termios.TCIOFLUSH)

    def read(self, timeout=0.1, size=4096):
        ready, _, _ = select.select([self.fd], [], [], timeout)
        if not ready:
            return b""
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return b""

    def write(self, payload):
        view = memoryview(payload)
        while view:
            _, ready, _ = select.select([], [self.fd], [], 2.0)
            if not ready:
                raise SerialError("timed out writing to the serial port")
            view = view[os.write(self.fd, view) :]

    def flush_input(self):
        termios.tcflush(self.fd, termios.TCIFLUSH)

    def close(self):
        try:
            os.close(self.fd)
        except OSError:
            pass
