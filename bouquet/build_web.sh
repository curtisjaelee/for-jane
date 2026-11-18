#!/usr/bin/env bash
# Blender → bouquet.glb → compressed → web/bouquet.glb
# Needs: Blender 4.2+ (set BLENDER=/path/to/blender if it isn't on PATH) and Node.js (for npx).
set -euo pipefail
cd "$(dirname "$0")"
BLENDER="${BLENDER:-blender}"

echo "→ Building the bouquet in Blender…"
"$BLENDER" --background --python blender/bouquet.py -- --glb --out blender/out

echo "→ Compressing (Draco geometry, WebP textures)…"
npx --yes @gltf-transform/cli optimize blender/out/bouquet.glb web/bouquet.glb \
  --compress draco --texture-compress webp \
  --flatten false --join false --instance false --simplify false --palette false

ls -lh web/bouquet.glb
echo "✓ Done. Open web/ with any static server, e.g.:  npx serve web"
