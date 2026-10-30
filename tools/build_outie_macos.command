#!/bin/bash
# Build locally; install Python dependencies only in this checkout's build directory.
set -euo pipefail

fail() { printf '\n%s\n' "$*" >&2; exit 1; }
[[ "$(uname -s)" == Darwin ]] || fail 'Run this helper on macOS.'
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# Finder does not inherit the PATH of an interactive Homebrew shell.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
PYTHON="${OUTIE_PYTHON:-python3}"
command -v "$PYTHON" >/dev/null || fail 'Install Python 3.11 or later, then retry.'
"$PYTHON" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 or later is required"'
[[ "$(sysctl -in sysctl.proc_translated 2>/dev/null || true)" != 1 ]] || fail 'Use a native Terminal and Python, not Rosetta, for this build.'
[[ "$("$PYTHON" -c 'import platform; print(platform.machine())')" == "$(uname -m)" ]] || fail 'Python must match this Mac architecture. Set OUTIE_PYTHON to a native interpreter.'
xcrun --find clang >/dev/null 2>&1 || fail 'Install Apple Command Line Tools with xcode-select --install, then retry.'
FFMPEG="$(command -v ffmpeg || true)"
FFPROBE="$(command -v ffprobe || true)"
[[ -n "$FFMPEG" && -n "$FFPROBE" ]] || fail 'Install FFmpeg and FFprobe (for example: brew install ffmpeg), then retry.'
"$FFMPEG" -version >/dev/null
"$FFPROBE" -version >/dev/null

BUILD="$ROOT/build/macos"
mkdir -p "$BUILD"
exec > >(tee "$BUILD/build.log") 2>&1
printf 'VolcaStudio XL Desktop App — local macOS build (%s)\n' "$(uname -m)"
printf 'Build log: %s/build.log\n' "$BUILD"
"$PYTHON" -m venv "$BUILD/venv"
PYTHON="$BUILD/venv/bin/python"
"$PYTHON" -m pip install -r packaging/requirements-outie.txt
"$PYTHON" -m pip freeze > "$BUILD/python-requirements.txt"
"$PYTHON" -c 'import platform, sys; print(platform.platform()); print(sys.version)' > "$BUILD/environment.txt"
"$FFMPEG" -version >> "$BUILD/environment.txt"
"$FFPROBE" -version >> "$BUILD/environment.txt"
"$PYTHON" tools/build_syro.py --compiler /usr/bin/clang
QT_QPA_PLATFORM=offscreen QT_QPA_PLATFORMTHEME=none "$PYTHON" -m unittest discover -s tests -p 'test_outie*.py' -v
export PYINSTALLER_CONFIG_DIR="$BUILD/pyinstaller-cache"
"$PYTHON" tools/build_outie.py --ffmpeg "$FFMPEG" --ffprobe "$FFPROBE" --output-root "$BUILD/package"
APP="$BUILD/package/dist/VolcaStudio XL Desktop App.app"
[[ -d "$APP" ]] || fail 'The build did not produce the expected .app bundle.'
# This mode uses temporary settings and never enumerates or opens audio/MIDI.
"$APP/Contents/MacOS/VolcaStudio XL Desktop App" --smoke-test
printf 'Packaged offline startup: PASS\n' >> "$BUILD/environment.txt"
VERIFY="$BUILD/offline-verification-$(date +%Y%m%d-%H%M%S)-$$"
"$APP/Contents/MacOS/VolcaStudio XL Desktop App" --verify-offline "$VERIFY"
printf 'Offline verification: %s\n' "$VERIFY" >> "$BUILD/environment.txt"
mkdir -p "$ROOT/dist"
ARCHIVE="$ROOT/dist/VolcaStudio-XL-Desktop-macOS-$(uname -m)-local.zip"
ditto -c -k --sequesterRsrc --keepParent "$APP" "$ARCHIVE"
printf '\nBuild and offline startup passed.\nApplication: %s\nArchive: %s\n' "$APP" "$ARCHIVE"
printf 'Next: open the app and run the macOS checks. No instrument transfer was performed.\n'
