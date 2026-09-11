#!/usr/bin/env bash
# Build a Windows-safe copy of mobile_print_agent (APK + source only).
# Use this instead of copying the whole folder — node_modules/android/.expo
# contain image/build paths that exceed Windows MAX_PATH.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="${1:-}"

if [[ -z "$OUT" ]]; then
  echo "Usage: $0 <output-directory>" >&2
  echo "Example: $0 /mnt/e/SmartWagersReleases/mobile_print_agent" >&2
  exit 1
fi

APK="$ROOT/dist/SmartWagers-PrintCompanion.apk"
if [[ ! -f "$APK" ]]; then
  echo "ERROR: missing $APK — run npm run build:android first." >&2
  exit 1
fi

mkdir -p "$OUT/dist" "$OUT/assets" "$OUT/src" "$OUT/patches"
cp -a "$APK" "$OUT/dist/"
cp -a "$ROOT/dist/README.md" "$OUT/dist/" 2>/dev/null || true

# Source / config only (short paths — safe on Windows)
for name in \
  .gitignore App.tsx README.md app.json babel.config.js eas.json \
  expo-env.d.ts package.json package-lock.json tsconfig.json
do
  [[ -f "$ROOT/$name" ]] && cp -a "$ROOT/$name" "$OUT/"
done

cp -a "$ROOT/assets/." "$OUT/assets/"
cp -a "$ROOT/src/." "$OUT/src/"
cp -a "$ROOT/patches/." "$OUT/patches/" 2>/dev/null || true

# Explicitly do NOT copy: node_modules, android, ios, .expo
cat > "$OUT/DO_NOT_COPY_BUILD_DIRS.txt" <<'EOF'
This folder is Windows-safe.

Never add these from the dev tree (they cause "file name is too long"):
  node_modules/
  android/
  ios/
  .expo/

Production only needs dist/SmartWagers-PrintCompanion.apk for Admin downloads.
EOF

echo "Wrote Windows-safe mobile_print_agent to: $OUT"
du -sh "$OUT"
