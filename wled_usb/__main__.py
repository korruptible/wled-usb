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

ROOT = pathlib.Path(__file__).resolve().parent.parent
PREFERRED = ("usbserial", "usbmodem", "wchusbserial", "slab_usbtouart", "cu.usb")
IGNORED = ("bluetooth", "debug-console")


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
        sys.exit("Aucun port série USB détecté. Branchez le module ou passez --port.")
    if len(found) > 1:
        print("Plusieurs ports possibles :")
        for _, device, description in found:
            print(f"  {device}  ({description})")
        print(f"→ utilisation de {found[0][1]} (forcez avec --port)")
    return found[0][1]


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="wled-usb",
        description="Pont USB série ↔ interface web officielle WLED",
    )
    parser.add_argument("--port", help="port série (défaut : détection automatique)")
    parser.add_argument("--baud", type=int, default=115200, help="débit série (défaut 115200)")
    parser.add_argument("--listen", default="localhost,tailscale,netbird",
                        help="adresses d'écoute séparées par des virgules : une IP, "
                             "ou localhost / tailscale / netbird (défaut : les trois)")
    parser.add_argument("--http-port", type=int, default=8723, help="port HTTP (défaut 8723)")
    parser.add_argument("--chip", default="esp32", help="cible esptool (défaut esp32)")
    parser.add_argument("--presets", default=str(ROOT / "data" / "presets.json"))
    parser.add_argument("--notifications", default=str(ROOT / "data" / "notifications.json"))
    parser.add_argument("--no-kdeconnect", action="store_true",
                        help="ne pas surveiller les notifications KDE Connect")
    parser.add_argument("--poll", type=float, default=2.0, help="intervalle de rafraîchissement")
    parser.add_argument("--audio-stdin", action="store_true",
                        help="lire des trames de bandes audio sur l'entrée standard")
    parser.add_argument("--audio-fps", type=int, default=25, help="images LED par seconde")
    parser.add_argument("--audio-mode", default="spectre", help="rendu audio au démarrage")
    parser.add_argument("--audio-config", default=str(ROOT / "data" / "audio.json"),
                        help="fichier des réglages audio")
    parser.add_argument("--open", action="store_true", help="ouvrir le navigateur au démarrage")
    parser.add_argument("--list-ports", action="store_true", help="lister les ports et quitter")
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

    notifier = Notifier(bridge, args.notifications)
    audio = AudioEngine(bridge, fps=args.audio_fps, mode=args.audio_mode,
                        config_path=args.audio_config)
    notifier.audio = audio
    sources = {}
    if not args.no_kdeconnect:
        sources["kdeconnect"] = KdeConnectSource(notifier)

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
                                         notifier, sources, audio, hosts)))
        except OSError as exc:
            print(f"Écoute     : {label} {address} impossible ({exc})")

    if not servers:
        print("Aucune adresse d'écoute disponible.", file=sys.stderr)
        link.stop()
        return 1

    print(f"Port série  : {port} @ {args.baud}")
    for label, address, _ in servers:
        print(f"Interface   : {url(address, args.http_port)} ({label})")
    for label in missing:
        print(f"Interface   : {label} indisponible, ignoré")
    exposed = [address for _, address, _ in servers if public(address)]
    if exposed:
        print(f"ATTENTION   : {', '.join(exposed)} est routable publiquement, "
              "et le pont n'a aucune authentification")
    for name, source in sources.items():
        print(f"Source {name}: {source.status()['detail']}")
    print("Ctrl+C pour arrêter.")

    for _, _, server in servers:
        threading.Thread(target=server.serve_forever, name="wled-http",
                         daemon=True).start()

    if args.open:
        threading.Timer(1.0, lambda: webbrowser.open(url(servers[0][1], args.http_port))).start()

    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\nArrêt…")
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
