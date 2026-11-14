#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/LuLu Research.app"
mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
/usr/bin/swiftc "$root/desktop/main.swift" -o "$app/Contents/MacOS/ResearchAgent"
cp "$root/desktop/Info.plist" "$app/Contents/Info.plist"
iconset="$(mktemp -d)/LuLu.iconset"
mkdir -p "$iconset"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" "$root/desktop/assets/lulu.png" --out "$iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" "$root/desktop/assets/lulu.png" --out "$iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$iconset" -o "$app/Contents/Resources/LuLu.icns"
find "$iconset" -type f -delete
rmdir "$iconset" "$(dirname "$iconset")"
legacy_app="$root/Research Agent.app"
if [ -d "$legacy_app" ]; then
    mkdir -p "$legacy_app/Contents/MacOS" "$legacy_app/Contents/Resources"
    cp "$app/Contents/MacOS/ResearchAgent" "$legacy_app/Contents/MacOS/ResearchAgent"
    cp "$app/Contents/Info.plist" "$legacy_app/Contents/Info.plist"
    cp "$app/Contents/Resources/LuLu.icns" "$legacy_app/Contents/Resources/LuLu.icns"
fi
printf '%s\n' "$app"
