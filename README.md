# wled-usb — control WLED over USB serial, without WiFi

Drive a **WLED** LED controller over **USB serial only**, with **no network access to the
device**, and serve the **official WLED web interface** locally.

Useful when the module must not join a network: a corporate or guest WiFi you cannot put
an IoT device on, an air-gapped bench, or simply not wanting one more ESP32 exposed at
home. WLED's own settings pages assume a web server on the device; this bridge gives you
the real control interface without one.

*[Version française](README.fr.md) · the interface itself is bilingual (English/French)
and follows your computer's language.*

WLED's firmware already speaks JSON on its serial port: anything starting with `{` is
handed to `deserializeState()`, and `{"v":true}` makes it answer with full state. The
bridge translates the official UI's HTTP requests onto that channel.

Developed and tested against WLED 16.0.1 on an ESP32-PICO-D4, 144 LEDs, macOS 27 on Apple
Silicon. The bridge itself is plain Python and has nothing macOS-specific; the menu bar
app described below does.

## Install

Python 3.10 or newer, and a WLED module on USB.

```bash
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt
./run.sh --open
```

The serial port is detected automatically. Useful options:

| Option | Effect |
| --- | --- |
| `--list-ports` | list candidate serial ports and exit |
| `--port /dev/cu.xxx` | force the port |
| `--http-port 8723` | HTTP port (default 8723) |
| `--listen localhost` | listen addresses (default: loopback only) |
| `--lang en` | interface language on first run |
| `--kdeconnect` | watch phone notifications through KDE Connect (off by default) |
| `--poll 2.0` | state refresh interval, in seconds |
| `--baud 115200` | serial baud rate |

The serial port is held **exclusively**: a second bridge instance, a serial monitor or
LedFx started alongside is refused with a clear message instead of silently sharing the
stream. Without that lock the two readers steal each other's answers, and the interface
stays empty while the link still looks "connected".

Two pages:

- `http://127.0.0.1:8723/` — the official WLED interface;
- `http://127.0.0.1:8723/bridge` — link status, presets, audio, firmware flashing.

## What works

All real-time control: power, brightness, colours, effects, palettes, speed and
intensity, segments, nightlight, transitions, preset loading. Effect and palette lists,
their slider metadata and the preview gradients are served by the bridge (see *Static
data*), and so is the live pixel preview.

| Endpoint | Source |
| --- | --- |
| `/json/si`, `/json/state`, `/json/info` | serial port, live |
| `POST /json`, `/json/state`, `/json/si` | serial port, live |
| `/json/effects`, `/json/palettes`, `/json/fxdata`, `/json/palx` | generated static database |
| `/json/live` and binary WebSocket frames | serial command `L` (pixel readback) |
| `/presets.json` | the bridge's local cache |
| `/ws` | state broadcast, commands, liveview |

## What is not possible, and why

WLED's serial handler only ever calls `deserializeState()`. **Configuration
(`deserializeConfig`) is never reached over the serial port.** The settings pages, the
file editor and OTA updates live only in the device's HTTP server, out of reach here.
Those URLs return an explanatory page.

Changing a persistent setting (LED count, pin, WiFi…) means going over the network once,
or flashing an image that carries the configuration you want.

### Presets

Preset *names* live in the device's filesystem and never travel over the serial port, so
the bridge keeps its own list in `data/presets.json`. Renaming in `/bridge` writes
nothing to the module. Scanning loads each slot in turn and restores the previous state
afterwards — the LEDs will visibly cycle.

## Firmware update over USB

The `/bridge` page uploads a `.bin` and runs esptool with the serial port released for
the duration, streaming its log back. By default only the **application** is written at
`0x10000`, so bootloader, partition table, filesystem and configuration survive.

> The bundled effect database must match the firmware you flash, or effect names will be
> off by one. The `/bridge` page reports the mismatch.

### Backup and rollback

Before reflashing, keep a way back: a full flash image, the device state (`/json`) and
the effect database for the version in place.

> `backup/` is **excluded from the repository** by `.gitignore`, and should stay that
> way. A full image contains the NVS partition, where the ESP32 stores the WiFi SSID and
> key in clear text, plus the module's MAC address. It is a personal backup, not a
> project artifact.

Reading a full image and restoring it:

```bash
./.venv/bin/python -m esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  read-flash 0 0x400000 backup/full-flash.bin
./.venv/bin/python -m esptool --chip esp32 --port /dev/cu.usbserial-XXXX --baud 115200 \
  write-flash 0x0 backup/full-flash.bin
```

Stop the bridge first: it holds the port exclusively. Changing baud rate after the stub
loader failed on this adapter, so stay at 115200.

### Going from 0.15.x to 16.x

Same partition table (`WLED_ESP32_4MB_1MB_FS.csv`), so writing the application alone at
`0x10000` is enough and the configuration is kept. The platform does jump from ESP-IDF
3.3 to 4.4.8 while the bootloader in flash stays the 0.15 one. Tested here on an
ESP32-PICO-D4; the module boots fine.

## Static data

`data/wled-data.json` holds the 220 effect names, their slider metadata, the 72 palette
names and the preview gradients. It is extracted from tagged WLED sources, not typed by
hand:

```bash
./.venv/bin/python tools/gen-data.py v16.0.1      # download the tag's sources and regenerate
./.venv/bin/python tools/gen-data.py --src ./srcs # from local sources
```

The generator reads `FX.h` (the `FX_MODE_*` indices), the `_data_FX_MODE_*` strings in
`FX.cpp` in `setupEffectData()` registration order, `JSON_palette_names` from
`FX_fcn.cpp`, the gradients and the 16-colour palettes. It mirrors WLED's own
`serializeModeNames`, `serializeModeData` and `serializePalettes`.

Both source layouts are recognised. Up to 0.15.x the gradients live in
`wled00/palettes.h` and the 16-colour palettes come from FastLED. From 16.x on, FastLED
is no longer a dependency: everything is in `wled00/palettes.cpp`, with the colour names
in `wled00/src/dependencies/fastled_slim/fastled_slim.h`. The generator picks a layout by
testing whether `palettes.h` exists on the requested tag.

The bridge compares the `fxcount`, `palcount` and `ver` reported by the module against
this database and flags any divergence in `/bridge/status`.

## Vendored interface

`vendor/` holds the official WLED **16.0.1** UI, taken from `wled00/data/` at that tag.
The UI version does not have to match the firmware: effect and palette lists come from
the bridge, not from the page, so an older UI drives a newer module perfectly well. Two
files are modified:

- `index.htm`: a **Bridge** button in the tab bar, linking to `/bridge`;
- `index.js`: the WebSocket fallback used `window.location.hostname`, which drops the
  port and would dial `ws://127.0.0.1/ws` on port 80. It now uses `window.location.host`.

`index.css`, `liveview.htm`, `iro.js` and `rangetouch.js` are untouched.
`public/skin.css` is the theming hook WLED itself provides, served as is.

WLED 16 added an update-check banner that reads `/json/cfg`, `/edit` and `/upload` and
posts device details to an external service. It suppresses itself when the module reports
access-point mode, which is exactly the case here, so nothing is requested and nothing
leaves the machine — verified by watching the network panel on a full page load. The
bridge serves none of those three endpoints anyway.

## Language

The interface ships in **English (default) and French**. On first run the bridge picks a
language from the computer's locale; the selector in the top-right corner of `/bridge`
overrides it, and the choice is stored and shared by the web page and the macOS menu.

Renderer and palette names are stable English keys on the API (`spectrum`, `bass`,
`rainbow`, `forest`…) and only translated for display, so saved settings survive a
language change. Terminal output is English only.

## macOS menu bar app

`app/` builds a self-contained `WLED USB.app`: it embeds its own CPython, starts the
bridge, captures system audio, and puts a menu in the status bar. `./app/build.sh`
downloads and checksums a relocatable interpreter, compiles the Swift, and signs the
bundle.

Signing uses a self-signed certificate named `WLED USB Dev` (override with
`WLED_SIGN_IDENTITY`). Without one the build falls back to ad-hoc signing, and macOS
re-asks for the audio permission on every rebuild. Apple Silicon only.

### Triggers

macOS offers **no API to read other applications' notifications**: neither
`UserNotifications`, which only sees its own, nor `DistributedNotificationCenter`, which
is too limited. That is an Apple design decision, so Slack on the Mac is out of reach
whatever language the app is written in.

What *is* observable without any permission, the app watches. Each trigger is enabled
separately from the menu and posts to `/bridge/notify` exactly as `notify.sh` would.

| Trigger | Source | Pattern |
| --- | --- | --- |
| Mac wakes up | `NSWorkspace.didWakeNotification` | `info` |
| Screen locked / unlocked | `com.apple.screenIsLocked` / `…Unlocked` | `info` |
| A watched app starts or quits | `NSWorkspace.did{Launch,Terminate}Application` | `slack` |
| Tailscale or NetBird goes down | `getifaddrs` sweep for a `100.64/10` address | `urgent` |
| Meeting in 5 minutes | EventKit | `call` |

Watched applications are chosen in *Triggers → Watched applications*: the submenu lists
running apps along with those already ticked, and the selection is kept in the app's
preferences.

Only the meeting trigger needs a permission — calendar access, narrow and revocable. It
is requested when you tick that line, never at launch.

### URL scheme

The app registers `wledusb://`, which puts the strip within reach of anything: a script,
an automation, a Stream Deck, or the **Open URL** action in Shortcuts.

```bash
open "wledusb://notify?pattern=slack&title=Build%20done&app=CI"
```

Parameters: `pattern`, `title`, `app`, `priority`. It is the same queue as KDE Connect
notifications, so priorities and anti-repeat rules apply.

## Computer audio to the LEDs

WLED's audio sync runs over UDP and does not exist on the serial port: `handleSerial()`
only knows Adalight, TPM2, Improv and JSON. So the analysis happens on the computer, and
only pixels go down the cable.

```
app (Swift) ──Core Audio tap──▶ vDSP FFT ──24 bands──▶ bridge (Python) ──Adalight──▶ module
```

The app opens a *Core Audio process tap*: no driver, no administrator password, and the
permission it asks for is "system audio recording", not screen recording. It captures the
mix whatever the output device is, headphones included, with no multi-output device to
build. Capture only starts when you click the menu item.

Bands arrive on the bridge's standard input (`--audio-stdin`), as
`A5 5A <n> <rms> <n bytes>` frames.

Each band is normalised separately: the engine keeps a sliding ceiling per band and
scales the level against it. Without that, the bass saturates while the treble stays
black and the strip barely moves. Pixels keep a trail (`PIXEL_DECAY`) to soften flicker.

Palettes are ramps of **saturated** colours, not dark-to-light gradients: brightness comes
from the sound level, not from the ramp. A dark first stop would dim the bass zone, which
is exactly the most visible one.

Normalising is not enough on its own — the strip only followed the large swings. Several
settings recover the small variations, all exposed in the `/bridge` panel:

| Setting | Role |
| --- | --- |
| `curve` (detail) | exponent applied to the normalised level. The lower it is, the more quiet levels are lifted: at 0.55 a level of 0.02 shows at 0.19 instead of staying black. |
| `palette` | colour ramp: `rainbow`, `ember`, `ocean`, `forest`, `neon`, `ice`, `sunset`. |
| `floor` | background glow applied **at the output**, on the LEDs the renderer leaves black. |
| `auto` | automatic gain: follows the source's loudness on its own. The `gain` slider then becomes the fill level aimed for at peaks. |

A presence gate, keyed on the raw RMS, keeps the strip dark in silence — without it the
floor would light the LEDs permanently.

Per-band normalisation flattens **timbre**, not **volume**: a podcast and a loudly
mastered track do not arrive at the same level, and the gain slider had to be nudged every
time. The automatic gain closes that loop. Each renderer declares in `DRIVES` the quantity
it multiplies by the gain — peak band for `spectrum`, bass average for `bass`, and so on —
and the engine follows it with a peak detector with fast attack (0.3 per frame) and slow
release (0.01, a few seconds). The applied gain is `gain × (1 / envelope)`, clamped between
0.4× and 6×, and shown live under the slider.

The attack/release asymmetry is what matters: coming down fast avoids clipping on a kick
drum, going back up slowly avoids pumping between verses. The loop is frozen while the
presence gate is shut, otherwise the gain would run to the ceiling during silences and the
first sound would come back in your face.

Two lessons from use. The floor was first applied to the **level**, before rendering: no
visible effect, since `spectrum` and `bass` encode energy as bar length and 3% of a zone is
a third of an LED. It now acts on black pixels at the output, so it works in every
renderer.

And normalising each band against its own maximum removes the relief between bands: the
strip lights up uniformly and stops telling you anything. `AGC_MIX` keeps 35% of the
absolute level so the bass stays louder than the treble.

| Renderer | What it does |
| --- | --- |
| `spectrum` | six mirrored bars from the centre, one per frequency group |
| `bass` | a bar growing from the centre with low-end energy |
| `wave` | a pulse launched on each bass attack, travelling outwards |
| `pulse` | the whole strip in one colour, hue following the spectral centroid |

| Setting | Effect |
| --- | --- |
| `--audio-fps` | LED frame rate, 25 by default |
| `--audio-mode` | renderer at startup |
| `--audio-config` | settings file, read at launch and rewritten on every change |
| `POST /bridge/audio` | `{"mode":…, "gain":…, "auto":…, "fps":…, "curve":…, "floor":…}` live |
| `GET /bridge/audio` | frames sent and dropped, level, error |

A notification pauses the audio for the duration of its flash, then resumes it.

### Adalight rather than TPM2

Both work, but WLED's TPM2 counter divides each length byte separately:
`(0x01×256)/3 + 0xB0/3` gives 143 instead of 144. **The last LED stays dark.** Measured on
the module: 143/144 over TPM2, 144/144 over Adalight, whose counter is exact. So the bridge
sends Adalight.

### Baud rate and desynchronisation

Measured on this module with a 438-byte frame: **26.5 frames/s at 115200 baud**, and **236
at 921600** after a `0xB5`. The strip refreshes at 43 frames/s when idle, so 115200 is
plenty and stays the default.

Streaming at 25 frames/s, the strip's own rate measurably drops to 17: at 115200 a frame
takes 38 ms to arrive, and the ESP32 shares that time with its own output. It looks smooth,
but it is the real ceiling at that rate.

> Changing baud rate mid-stream is dangerous. WLED reads `0xB0`–`0xB7` as commands as soon
> as its state machine sits between frames; after a desynchronisation, an ordinary pixel
> byte becomes a command. It happened during testing: the module ended up at 460800 without
> being asked. If it happens to you, unplugging and replugging the module brings it back to
> its configured value.

## Audio-reactive streaming (LedFx, Adalight)

The same serial handler also accepts **Adalight** and **TPM2**, so software like LedFx can
drive the module over USB with an *Adalight* device (115200 baud, 144 LEDs). Effects are
then computed on the computer, unlike the bridge, which drives WLED's internal effects.

Only one program at a time can open the port: stop the bridge before starting LedFx. The
exclusive lock means one of the two refuses to start rather than corrupting the other's
link.

## Notifications

The strip doubles as an indicator: when a notification arrives it interrupts the current
scene, plays a coloured pattern, then **restores the previous state exactly** — power,
brightness, effect, palette, segment bounds, colours.

### Anything, over HTTP

The general way in is one endpoint, so whatever can make an HTTP request can light the
strip — a CI job, a cron, a Makefile, a Stream Deck:

```bash
curl -X POST http://127.0.0.1:8723/bridge/notify \
     -H 'Content-Type: application/json' \
     -d '{"app":"Jenkins","title":"deploy done","pattern":"info"}'
```

`notify.sh` wraps that for shell use, and `WLED_USB_URL` changes the address it targets:

```bash
./notify.sh CI "build broken" urgent
./notify.sh Slack "new message"
make test || ./notify.sh Tests "failed" urgent
```

### Optional: phone notifications through KDE Connect

Off by default, and useful only if you already run KDE Connect. Enable it with
`--kdeconnect`.

Notifications relayed by KDE Connect are read on the private D-Bus session its desktop
application starts for itself. The bridge looks for that session on its own, probing the
usual socket locations (`/tmp/dbus-*`, `/run/user/*/bus`) for the name
`org.kde.kdeconnect`, then polls `activeNotifications` every 2 seconds and reacts to new
entries. `--kdeconnect-bus` gives an explicit address instead, and
`DBUS_SESSION_BUS_ADDRESS` is honoured when set.

It reads only `appName` and `title`. **Message bodies are never read, logged or sent
anywhere.** The log stays in memory and disappears when the bridge stops.

Requires `gdbus` — `brew install glib` on macOS, usually already present on Linux — and
KDE Connect paired with the phone. The menu bar app leaves it off unless asked:

```bash
defaults write fr.wledusb.app kdeconnect -bool true
```

### Patterns and rules

Edited in the `/bridge` page, stored in `data/notifications.json`. A pattern defines a
colour, an LED count, a brightness and a number of flashes; a rule maps an application name
to a pattern. With no matching rule, `defaultPattern` applies.

Identical notifications received within the `coalesceSeconds` window are grouped, and
`quietHours` silences the strip over a time range.

### Current budget

**Read this if your LEDs are powered by the microcontroller.** WLED's current limiter
(*Automatic Brightness Limiter*) defaults to 2000 mA, far above what a USB port supplies.
Asking for more than the supply can give drops the voltage and **the module reboots** —
nothing to do with notifications, any bright full-strip scene does it.

Work out your own ceiling rather than copying anyone's figures. As an order of magnitude,
an RGB LED draws up to about 55 mA at full white, the controller itself takes around
100 mA idle, and the draw scales with brightness and with how many channels the colour
lights. A 500 mA USB port therefore runs out well before a long strip reaches full
brightness.

The numbers below come from **one** setup — a 144-LED WS2812B strip on USB power — and
are here to show the shape of the curve, not to be reused:

| Scene | Current estimated by WLED |
| --- | --- |
| 20 LEDs @ bri 140 | 389 mA |
| 40 LEDs @ bri 140 | 659 mA |
| 144 LEDs @ bri 30 | 536 mA |
| 144 LEDs @ bri 60 | 952 mA |
| 144 LEDs @ bri 160, bright colour | brownout |

Note how little brightness a full strip can take: 144 LEDs at `bri 60`, less than a
quarter of the range, already draws more than a USB port gives.

Two protections:

1. Set the module's limiter (*Maximum Current*) to a realistic value — 400 to 500 mA for a
   USB supply. That setting is **not reachable over the serial port**: you have to go
   through the device's web server once, for example via its access point
   (`http://4.3.2.1/settings/leds`).
2. On the bridge side, patterns light only part of the strip and their brightness is
   reduced automatically to stay under `powerBudgetMa`, itself capped by the limit the
   module reports in `info.leds.maxpwr`. It defaults to 700 mA, which assumes USB power —
   raise it in `/bridge` if your strip has a supply of its own, along with `ledMilliamps`
   if your LEDs are not ordinary RGB.

### Why desktop notifications cannot be mirrored

macOS exposes no API for reading another application's notifications, so the bridge
cannot reflect what your desktop apps are showing — a chat app, a mail client, a build
tool. This is not an omission; every route around it needs a permission far wider than
the task:

- the Notification Center database (`group.com.apple.usernoted`) needs **Full Disk
  Access**;
- reading an application's Dock badge through System Events needs an **Automation**
  permission, and returns error `-1743` without it;
- `lsappinfo` no longer returns anything usable (checked on macOS 27).

That is why the triggers above watch only what is observable without asking for
anything. Where an application also runs on a phone paired with KDE Connect, its
notifications arrive by that route instead, carrying their own `appName` — which a rule
can then map to a pattern.

## Architecture

```
wled_usb/serialport.py  raw termios open (CLOCAL, leaving DTR/RTS alone)
wled_usb/link.py        serial transactions, JSON line and TPM2 parser, reconnection
wled_usb/bridge.py      state cache, polling, WebSocket broadcast, liveview
wled_usb/httpd.py       HTTP + WebSocket server, WLED API emulation
wled_usb/flash.py       esptool driver with port release
wled_usb/presets.py     local preset cache
wled_usb/data.py        static effect and palette database
wled_usb/audio.py       audio-reactive renderers, automatic gain, Adalight output
wled_usb/listen.py      listen address resolution (localhost, Tailscale, NetBird)
wled_usb/ui.py          shared interface language preference
wled_usb/ws.py          minimal WebSocket framing
wled_usb/notify.py      notification engine: patterns, queue, budget, restore
wled_usb/kdeconnect.py  optional KDE Connect source (bus discovery, D-Bus polling)
app/Sources/            macOS app: audio capture, FFT, menu, triggers
public/                 the bridge's own pages (/bridge, unavailable page)
vendor/                 redistributed WLED web interface
tools/gen-data.py       effect and palette extraction from WLED sources
notify.sh               command-line trigger
```

Serial transport is deliberately raw `termios` rather than pyserial: pyserial drives
DTR/RTS on open, which **reboots the module** every time the bridge connects. A raw
`CLOCAL` open leaves those lines alone. pyserial is still installed — esptool depends on
it.

## Security

**By default the bridge binds loopback only.** It opens one socket per requested
address and never a wildcard: `0.0.0.0` is never bound, so nothing is reachable from the
local network even when the machine is on it. The module itself is on no network at all.

Missing CORS headers protect nothing: they stop a third-party page from **reading** the
answer, not from **posting** the request. Any web page open in your browser could therefore
drive the LEDs — and, worse, reach `POST /bridge/flash`, which writes arbitrary firmware to
the module. So the bridge checks two headers on every request:

| Header | Check | What it blocks |
| --- | --- | --- |
| `Host` | must match a listen address | DNS rebinding: a hostile domain resolving to `127.0.0.1` |
| `Origin` | when present, must be one of the bridge's own | requests issued by a third-party page, WebSocket included |

A missing `Origin` is accepted: that is the case for `curl`, `notify.sh` and scripts. The
threat model is the browser, and a browser always attaches `Origin` to a cross-origin
request.

### Optional: reaching the bridge from another machine

Everything in this section is opt-in and off unless you ask for it. `--listen` takes a
comma-separated list mixing literal addresses and keywords:

```bash
./run.sh --listen localhost,192.168.1.42   # a literal address
./run.sh --listen localhost,tailscale      # whatever address Tailscale gives this host
```

| Keyword | Resolution |
| --- | --- |
| `localhost` | `127.0.0.1` |
| `tailscale` | output of `tailscale ip` (IPv4 and IPv6) |
| `netbird` | `NetBird IP` / `NetBird IPv6` lines from `netbird status` |

The two overlay-network keywords exist because a private mesh is about the only sane way
to expose a service that has no authentication. They are conveniences, not requirements:
the addresses are resolved at startup by running the client, never hard-coded, since they
change with the mesh. A keyword whose client is missing or disconnected is reported and
skipped, an address already in use does not stop the others from opening, and the bridge
only refuses to start when no address is left at all.

The menu bar app passes `localhost` unless you tell it otherwise:

```bash
defaults write fr.wledusb.app listen "localhost,tailscale"
```

A warning is printed if a bound address turns out to be publicly routable. Tailscale's
ranges (`100.64.0.0/10`, `fd7a:115c:a1e0::/48`) and NetBird's are not.

> **The bridge has no authentication.** Anything that reaches the port can drive the LEDs
> and flash the firmware. On a mesh network that means every peer, and every device the
> machine is shared with.

## How this was built

Much of this code was written with an AI assistant (Claude Code), working with a human
who owns the hardware and ran everything on it. Saying so plainly seems better than
leaving you to work it out.

Two things follow, and they cut both ways:

- The numbers in this README were measured, not guessed — frame rates, current draw, the
  TPM2 off-by-one that leaves the last LED dark, the baud desynchronisation. Each one
  came from running the device and reading what came back. Where something was not
  measured, the text says so.
- One pair of eyes reviewed the result. Read the code before trusting it with your
  hardware, as you would with any small project.

## Licence and credits

This project is under the **EUPL v. 1.2 or later**, like WLED, because it redistributes
WLED's web interface and data extracted from its sources. See `LICENSE` for the text and
`NOTICE` for the third-party components: WLED UI (EUPL-1.2), iro.js (MPL-2.0),
rangetouch.js (MIT).

Firmware binaries are not versioned. `firmware/*.bin` is excluded by `.gitignore`; get the
version you want from the [WLED releases page](https://github.com/wled/WLED/releases) and
check its digest before flashing:

```bash
shasum -a 256 firmware/WLED_16.0.1_ESP32.bin
# 628917b0753edcfc9a8408e6387c6d1ace6a360d315441e9563d60299fef8594
```

<sub>made with ❤️ by Matthieu Jeannin 🇫🇷</sub>
