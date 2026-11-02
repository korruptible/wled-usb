from __future__ import annotations

import argparse
import pathlib
import sys
import threading
import webbrowser

from serial.tools import list_ports

from .bridge import Bridge
from .data import StaticData
from .flash import Flasher
from .httpd import BridgeServer, known_hosts
from .kdeconnect import KdeConnectSource
from .audio import AudioEngine
from .link import WledLink
from .listen import ListenError, public, resolve, url
from .notify import Notifier
from .presets import PresetStore
from .ui import UiSettings

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREFERRED = ("usbserial", "usbmodem", "wchusbserial", "slab_usbtouart", "cu.usb",
             "ttyusb", "ttyacm")
IGNORED = ("bluetooth", "debug-console", "ttys")


def candidate_ports():
    found = []
    for entry in list_ports.comports():
        name = entry.device.lower()
        if any(bad in name for bad in IGNORED):
            continue
        rank = 0 if any(good in name for good in PREFERRED) else 1
        found.append((rank, entry.device, entry.description))
    return sorted(found)


def pick_port(requested):
    if requested:
        return requested
    found = candidate_ports()
    if not found:
        sys.exit("No USB serial port found. Plug the module in, or pass --port.")
    if len(found) > 1:
        print("Several candidate ports:")
        for _, device, description in found:
            print(f"  {device}  ({description})")
        print(f"→ using {found[0][1]} (override with --port)")
    return found[0][1]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="wled-usb",
        description="USB serial bridge to the official WLED web interface",
    )
    parser.add_argument("--port", help="serial port (default: autodetect)")
    parser.add_argument("--baud", type=int, default=115200, help="serial baud rate (default 115200)")
    parser.add_argument("--listen", default="localhost",
                        help="comma-separated listen addresses: a literal IP, "
                             "or localhost / tailscale / netbird (default: localhost)")
    parser.add_argument("--http-port", type=int, default=8723, help="HTTP port (default 8723)")
    parser.add_argument("--chip", default="esp32", help="esptool chip target (default esp32)")
    parser.add_argument("--presets", default=str(ROOT / "data" / "presets.json"))
    parser.add_argument("--notifications", default=str(ROOT / "data" / "notifications.json"))
    parser.add_argument("--kdeconnect", action="store_true",
                        help="watch phone notifications relayed by KDE Connect (off by default)")
    parser.add_argument("--kdeconnect-bus",
                        help="explicit D-Bus address, instead of probing for one")
    parser.add_argument("--poll", type=float, default=2.0, help="state refresh interval, in seconds")
    parser.add_argument("--audio-stdin", action="store_true",
                        help="read audio band frames on standard input")
    parser.add_argument("--audio-fps", type=int, default=25, help="LED frames per second")
    parser.add_argument("--audio-mode", default="spectrum", help="audio renderer at startup")
    parser.add_argument("--audio-config", default=str(ROOT / "data" / "audio.json"),
                        help="audio settings file")
    parser.add_argument("--lang", help="interface language at first run (en, fr)")
    parser.add_argument("--ui-config", default=str(ROOT / "data" / "ui.json"),
                        help="interface settings file")
    parser.add_argument("--open", action="store_true", help="open the browser at startup")
    parser.add_argument("--list-ports", action="store_true", help="list the serial ports and exit")
    args = parser.parse_args(argv)

    if args.list_ports:
        for _, device, description in candidate_ports():
            print(f"{device}\t{description}")
        return 0

    try:
        listeners, missing = resolve(args.listen)
    except ListenError as exc:
        print(exc, file=sys.stderr)
        return 2

    port = pick_port(args.port)
    data = StaticData()
    link = WledLink(port, args.baud)
    presets = PresetStore(args.presets)
    bridge = Bridge(link, data, presets, poll_interval=args.poll)
    flasher = Flasher(link, chip=args.chip, python_exe=sys.executable)

    ui = UiSettings(args.ui_config, args.lang)
    notifier = Notifier(bridge, args.notifications)
    audio = AudioEngine(bridge, fps=args.audio_fps, mode=args.audio_mode,
                        config_path=args.audio_config)
    notifier.audio = audio
    sources = {}
    if args.kdeconnect:
        sources["kdeconnect"] = KdeConnectSource(notifier, address=args.kdeconnect_bus)

    link.start()
    bridge.start()
    notifier.start()
    if args.audio_stdin:
        audio.start(sys.stdin.buffer)
    for source in sources.values():
        source.start()

    hosts = known_hosts([address for _, address in listeners], args.http_port)
    servers = []
    for label, address in listeners:
        try:
            servers.append((label, address,
                            BridgeServer((address, args.http_port), bridge, flasher,
                                         notifier, sources, audio, hosts, ui)))
        except OSError as exc:
            print(f"Listen     : {label} {address} failed ({exc})")

    if not servers:
        print("No listen address available.", file=sys.stderr)
        link.stop()
        return 1

    print(f"Serial port : {port} @ {args.baud}")
    for label, address, _ in servers:
        print(f"Interface   : {url(address, args.http_port)} ({label})")
    for label in missing:
        print(f"Interface   : {label} unavailable, skipped")
    exposed = [address for _, address, _ in servers if public(address)]
    if exposed:
        print(f"WARNING     : {', '.join(exposed)} is publicly routable, "
              "and the bridge has no authentication")
    for name, source in sources.items():
        print(f"Source {name}: {source.status()['detail']}")
    print("Ctrl+C to stop.")

    for _, _, server in servers:
        threading.Thread(target=server.serve_forever, name="wled-http",
                         daemon=True).start()

    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url(servers[0][1], args.http_port))).start()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nStopping…")
    finally:
        for source in sources.values():
            source.stop()
        notifier.stop()
        bridge.stop()
        for _, _, server in servers:
            server.shutdown()
            server.server_close()
        link.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
