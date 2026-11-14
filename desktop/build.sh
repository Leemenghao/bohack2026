#!/bin/bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
app="$root/Research Agent.app"
mkdir -p "$app/Contents/MacOS"
/usr/bin/swiftc "$root/desktop/main.swift" -o "$app/Contents/MacOS/ResearchAgent"
cp "$root/desktop/Info.plist" "$app/Contents/Info.plist"
printf '%s\n' "$app"
