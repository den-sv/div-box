#!/bin/sh
# Builds "Timebox Bridge.app" from tbridge.swift with Apple's own compiler (Xcode Command Line Tools).
# Ad-hoc signed, never leaves your Mac. tb runs this automatically the first time.
set -e
cd "$(dirname "$0")"
APP="Timebox Bridge.app"
command -v swiftc >/dev/null || { echo "swiftc missing: run  xcode-select --install"; exit 1; }
mkdir -p "$APP/Contents/MacOS"
cp Info.plist "$APP/Contents/Info.plist"
swiftc -O tbridge.swift -o "$APP/Contents/MacOS/tbridge"
codesign -s - -f "$APP" 2>/dev/null
echo "built $APP"
