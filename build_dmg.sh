#!/bin/bash
# Build a drag-to-install DMG for HS Arena Plus.
# Layout: [App icon]  [Applications alias]  (user drags left→right)
#
# Usage:
#   ./build_dmg.sh                  # uses dist/HS Arena Plus.app
#   ./build_dmg.sh --build          # runs py2app first, then packages

set -e

APP_NAME="HS Arena Plus"
DMG_FINAL="dist/HSArenaPlus.dmg"
APP_SRC="dist/${APP_NAME}.app"
VOLUME_NAME="HS Arena Plus"
DMG_TMP="/tmp/HSArenaPlus_rw.dmg"

# ── Optional: build app first ─────────────────────────────────────────────────
if [[ "$1" == "--build" ]]; then
    echo "=== Building app bundle ==="
    source .venv/bin/activate 2>/dev/null || true
    python setup.py py2app 2>&1 | tail -5
fi

# ── Validate source ───────────────────────────────────────────────────────────
if [[ ! -d "$APP_SRC" ]]; then
    echo "ERROR: $APP_SRC not found. Run './build_dmg.sh --build' or 'python setup.py py2app' first."
    exit 1
fi

echo "=== Packaging: $APP_NAME → $DMG_FINAL ==="

# ── Clean up ──────────────────────────────────────────────────────────────────
rm -f "$DMG_FINAL" "$DMG_TMP"
# Detach any leftover mount from previous failed run
hdiutil detach "/Volumes/$VOLUME_NAME" 2>/dev/null || true

# ── Stage folder (app + Applications symlink) ─────────────────────────────────
STAGE=$(mktemp -d)
cp -r "$APP_SRC" "$STAGE/${APP_NAME}.app"
ln -s /Applications "$STAGE/Applications"

# ── Create writable DMG from staged folder ────────────────────────────────────
hdiutil create \
    -volname "$VOLUME_NAME" \
    -srcfolder "$STAGE" \
    -ov \
    -format UDRW \
    "$DMG_TMP" > /dev/null

rm -rf "$STAGE"

# ── Mount the writable image ──────────────────────────────────────────────────
MOUNT_POINT="/Volumes/$VOLUME_NAME"
hdiutil attach -readwrite -noverify -noautoopen "$DMG_TMP" > /dev/null
echo "Mounted at: $MOUNT_POINT"
sleep 2

# ── Set window layout via Finder AppleScript ──────────────────────────────────
osascript << APPLESCRIPT
tell application "Finder"
    tell disk "$VOLUME_NAME"
        open
        delay 1
        set current view of container window to icon view
        set toolbar visible of container window to false
        set statusbar visible of container window to false
        set bounds of container window to {300, 150, 820, 450}
        set viewOptions to the icon view options of container window
        set arrangement of viewOptions to not arranged
        set icon size of viewOptions to 120
        set text size of viewOptions to 12
        set position of item "${APP_NAME}.app" of container window to {155, 145}
        try
            set position of item "Applications" of container window to {365, 145}
        end try
        update without registering applications
        delay 2
        close
    end tell
end tell
APPLESCRIPT

# Flush DS_Store to disk
sync
sleep 1

# ── Unmount ───────────────────────────────────────────────────────────────────
hdiutil detach "$MOUNT_POINT" > /dev/null

# ── Convert to compressed read-only final DMG ─────────────────────────────────
hdiutil convert "$DMG_TMP" \
    -format UDZO \
    -imagekey zlib-level=9 \
    -o "$DMG_FINAL" > /dev/null

rm -f "$DMG_TMP"

# ── Report ────────────────────────────────────────────────────────────────────
SIZE=$(du -sh "$DMG_FINAL" | cut -f1)
echo "=== Done: $DMG_FINAL ($SIZE) ==="
