#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"

NAME="WLED USB"
BUNDLE="build/$NAME.app"
RES="$BUNDLE/Contents/Resources"
RUNTIME="vendor/python-runtime"
ARCHIVE="vendor/cpython.tar.gz"
CERT_NAME="${WLED_SIGN_IDENTITY:-WLED USB Dev}"
PYTHON_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.14.10%2B20261026-aarch64-apple-darwin-install_only.tar.gz"
PYTHON_SHA="30a18bcb9ab75e485b4bf4e5d783dde165571e7e42c56dff47a2d2c5345183a4"

if security find-identity -v -p codesigning | grep -qF "$CERT_NAME"; then
	IDENTITY="$CERT_NAME"
else
	IDENTITY="-"
	echo "⚠  certificat « $CERT_NAME » introuvable : signature à la volée," >&2
	echo "   l'autorisation audio sautera à chaque reconstruction." >&2
fi

if [ ! -x "$RUNTIME/bin/python3" ]; then
	mkdir -p vendor
	if [ -f "$ARCHIVE" ] && ! shasum -a 256 -c --status <<<"$PYTHON_SHA  $ARCHIVE"; then
		echo "→ archive locale obsolète, elle est retéléchargée"
		rm -f "$ARCHIVE"
	fi
	if [ ! -f "$ARCHIVE" ]; then
		echo "→ téléchargement de l'interpréteur embarqué (27 Mo)"
		curl -fsSL -o "$ARCHIVE" "$PYTHON_URL"
	fi
	shasum -a 256 -c --status <<<"$PYTHON_SHA  $ARCHIVE" || {
		echo "empreinte inattendue pour $ARCHIVE, téléchargement abandonné" >&2
		exit 1
	}

	echo "→ extraction de l'interpréteur embarqué"
	rm -rf "$RUNTIME"
	mkdir -p "$RUNTIME"
	tar xzf "$ARCHIVE" -C "$RUNTIME" --strip-components=1
	"$RUNTIME/bin/python3" -m pip install --no-compile --quiet pyserial esptool
	find "$RUNTIME" -name '__pycache__' -type d -prune -exec rm -rf {} +
	rm -rf "$RUNTIME"/lib/python3.*/{test,idlelib,tkinter,turtledemo} \
	       "$RUNTIME/share" "$RUNTIME/include"
fi

rm -rf "$BUNDLE"
mkdir -p "$BUNDLE/Contents/MacOS" "$RES"

cat > "$BUNDLE/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>CFBundleName</key><string>$NAME</string>
	<key>CFBundleDisplayName</key><string>$NAME</string>
	<key>CFBundleIdentifier</key><string>fr.wledusb.app</string>
	<key>CFBundleExecutable</key><string>wled-usb</string>
	<key>CFBundlePackageType</key><string>APPL</string>
	<key>CFBundleShortVersionString</key><string>1.0</string>
	<key>CFBundleVersion</key><string>1</string>
	<key>LSMinimumSystemVersion</key><string>14.2</string>
	<key>LSUIElement</key><true/>
	<key>CFBundleIconFile</key><string>icon</string>
	<key>NSAudioCaptureUsageDescription</key>
	<string>Analyser le son du Mac pour animer les LEDs.</string>
	<key>NSCalendarsFullAccessUsageDescription</key>
	<string>Prévenir sur le ruban qu'une réunion va commencer.</string>
	<key>CFBundleURLTypes</key>
	<array><dict>
		<key>CFBundleURLName</key><string>fr.wledusb.app</string>
		<key>CFBundleURLSchemes</key><array><string>wledusb</string></array>
	</dict></array>
</dict>
</plist>
PLIST

swiftc -O \
	-target arm64-apple-macos14.2 \
	-framework AppKit -framework AudioToolbox -framework WebKit -framework EventKit \
	-o "$BUNDLE/Contents/MacOS/wled-usb" \
	Sources/*.swift

cp icon.icns "$RES/icon.icns"
cp -R "$RUNTIME" "$RES/python"
mkdir -p "$RES/bridge"
cp -R ../wled_usb "$RES/bridge/wled_usb"
mkdir -p "$RES/bridge/data"
cp ../data/wled-data.json "$RES/bridge/data/"
cp -R ../vendor "$RES/bridge/vendor"
cp -R ../public "$RES/bridge/public"
find "$RES/bridge" -name '__pycache__' -type d -prune -exec rm -rf {} +

codesign --force --deep --sign "$IDENTITY" --identifier fr.wledusb.app "$BUNDLE" 2>&1 \
	| grep -v "replacing existing signature" || true

touch "$BUNDLE"
echo "construit : $BUNDLE  ($(du -sh "$BUNDLE" | cut -f1))"
codesign -dv "$BUNDLE" 2>&1 | grep -E "Identifier|Signature" || true
