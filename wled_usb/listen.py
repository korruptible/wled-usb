from __future__ import annotations

import ipaddress
import re
import shutil
import subprocess

TAILSCALE_BINARIES = (
    "tailscale",
    "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    "/usr/local/bin/tailscale",
    "/opt/homebrew/bin/tailscale",
)
NETBIRD_BINARIES = ("netbird", "/usr/local/bin/netbird", "/opt/homebrew/bin/netbird")

LOOPBACK = ("127.0.0.1", "::1")


class ListenError(ValueError):
    pass


def _run(binaries, arguments):
    for binary in binaries:
        if "/" not in binary and shutil.which(binary) is None:
            continue
        try:
            done = subprocess.run([binary, *arguments], capture_output=True,
                                  text=True, timeout=5)
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0 and done.stdout.strip():
            return done.stdout
    return ""


def tailscale_addresses():
    out = _run(TAILSCALE_BINARIES, ["ip"])
    return [line.strip() for line in out.splitlines() if line.strip()]


def netbird_addresses():
    out = _run(NETBIRD_BINARIES, ["status"])
    found = []
    for line in out.splitlines():
        match = re.match(r"\s*NetBird IP(?:v6)?:\s*(\S+)", line)
        if match:
            found.append(match.group(1).split("/")[0])
    return found


TOKENS = {
    "localhost": lambda: list(LOOPBACK[:1]),
    "tailscale": tailscale_addresses,
    "netbird": netbird_addresses,
}


def resolve(spec):
    wanted = [item.strip() for item in spec.split(",") if item.strip()]
    if not wanted:
        raise ListenError("aucune adresse d'écoute demandée")

    resolved, seen, missing = [], set(), []
    for item in wanted:
        key = item.lower()
        if key in TOKENS:
            addresses = TOKENS[key]()
            if not addresses:
                missing.append(key)
        else:
            try:
                ipaddress.ip_address(item)
            except ValueError:
                raise ListenError(f"adresse d'écoute invalide : {item}") from None
            addresses, key = [item], "explicite"
        for address in addresses:
            if address not in seen:
                seen.add(address)
                resolved.append((key, address))
    return resolved, missing


def public(address):
    try:
        parsed = ipaddress.ip_address(address)
    except ValueError:
        return True
    return parsed.is_global


def url(address, port):
    host = f"[{address}]" if ":" in address else address
    return f"http://{host}:{port}/"
