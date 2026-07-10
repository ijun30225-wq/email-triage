#!/bin/zsh
# Build the Mac notification helper app.
# osacompile assigns a bundle ID under Script Editor's namespace, which makes
# notification clicks route to Script Editor — so we set our own ID and re-sign.
set -e
cd "$(dirname "$0")"
rm -rf "Email Triage.app"
osacompile -o "Email Triage.app" helper.applescript
plutil -replace CFBundleIdentifier -string "com.jun.email-triage.helper" "Email Triage.app/Contents/Info.plist"
plutil -replace CFBundleName -string "Email Triage" "Email Triage.app/Contents/Info.plist"
codesign -f -s - "Email Triage.app"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$PWD/Email Triage.app"
echo "Built. Allow notifications for 'Email Triage' when macOS asks."
