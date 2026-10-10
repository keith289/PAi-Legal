#!/usr/bin/env bash
set -e

SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
PROJECT_DIR="$SCRIPT_DIR"
BUILD_DIR="$PROJECT_DIR/build"
ARCHIVE_PATH="$BUILD_DIR/PAiLegalCompanion.xcarchive"
EXPORT_PATH="$BUILD_DIR/AppStore"

echo "=== PAi Legal iOS App Store Release Builder ==="

mkdir -p "$BUILD_DIR"

if command -v xcodebuild >/dev/null 2>&1; then
    echo "1. Archiving Xcode Project..."
    xcodebuild archive \
        -project "$PROJECT_DIR/PAiLegalCompanion.xcodeproj" \
        -scheme "PAiLegalCompanion" \
        -configuration Release \
        -archivePath "$ARCHIVE_PATH" \
        -destination "generic/platform=iOS"

    echo "2. Exporting App Store IPA..."
    xcodebuild -exportArchive \
        -archivePath "$ARCHIVE_PATH" \
        -exportOptionsPlist "$PROJECT_DIR/AppStoreExportOptions.plist" \
        -exportPath "$EXPORT_PATH"

    echo "=== Build Complete: IPA saved to $EXPORT_PATH ==="
    echo "Next: Upload $EXPORT_PATH/PAiLegalCompanion.ipa to App Store Connect via Transporter or 'xcrun altool'."
else
    echo "xcodebuild tool is not available on this platform (macOS required for iOS archive)."
    echo "Created App Store Export configuration at: $PROJECT_DIR/AppStoreExportOptions.plist"
fi
