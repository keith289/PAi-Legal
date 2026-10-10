#!/usr/bin/env bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
cd "$SCRIPT_DIR"

echo "=== PAi Legal Android Google Play Release Builder ==="

if [ -f "./gradlew" ]; then
    echo "1. Building Android App Bundle (AAB)..."
    ./gradlew bundleRelease
    echo "=== Build Complete: AAB saved to $SCRIPT_DIR/app/build/outputs/bundle/release/app-release.aab ==="
    echo "Next: Upload app-release.aab to Google Play Console."
else
    echo "Gradle wrapper './gradlew' not present. Creating Android project release configuration."
    echo "To build manually: Open $SCRIPT_DIR in Android Studio and select Build -> Generate Signed Bundle / APK."
fi
