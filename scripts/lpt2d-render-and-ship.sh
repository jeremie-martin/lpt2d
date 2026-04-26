#!/usr/bin/env bash
# Daily entry point: render an iris batch and ship completed bundles to the VPS.
# Wrapped in flock so concurrent timer firings don't double-render.
#
# Env knobs:
#   LPT2D_NIGHTLY_N        — bundles per nightly batch (default: 12)
#   LPT2D_NIGHTLY_RES      — width:height (default: 1080:1920)
#   LPT2D_NIGHTLY_FPS      — fps (default: 24)
#   LPT2D_NIGHTLY_DURATION — seconds per video (default: 60)
#   LPT2D_NIGHTLY_RAYS     — rays per pixel (default: 1000000)
#   LPT2D_NIGHTLY_DEPTH    — bounce depth (default: 10)
#   LPT2D_REMOTE           — see lpt2d-ship.sh
#   LPT2D_REMOTE_INBOX     — see lpt2d-ship.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCK_DIR="${XDG_RUNTIME_DIR:-/tmp}"
LOCK_FILE="$LOCK_DIR/lpt2d-render-and-ship.lock"

mkdir -p "$LOCK_DIR"
exec 9>"$LOCK_FILE"
if ! flock -n 9; then
    echo "[lpt2d] another render+ship is already running; skipping"
    exit 0
fi

cd "$ROOT"

N="${LPT2D_NIGHTLY_N:-12}"
RES="${LPT2D_NIGHTLY_RES:-1080:1920}"
WIDTH="${RES%%:*}"
HEIGHT="${RES##*:}"
FPS="${LPT2D_NIGHTLY_FPS:-24}"
DURATION="${LPT2D_NIGHTLY_DURATION:-60}"
RAYS="${LPT2D_NIGHTLY_RAYS:-1000000}"
DEPTH="${LPT2D_NIGHTLY_DEPTH:-10}"

TS="$(date -u +%Y%m%d)"
OUT="$ROOT/renders/lpt2d_iris_nightly_${TS}_${WIDTH}x${HEIGHT}_n${N}"

echo "[lpt2d] nightly render: out=$OUT n=$N res=${WIDTH}x${HEIGHT}@${FPS} dur=${DURATION}s"
uv run python examples/python/families/iris_batch.py \
    --out "$OUT" \
    -n "$N" \
    --width "$WIDTH" --height "$HEIGHT" \
    --fps "$FPS" --duration "$DURATION" \
    --rays "$RAYS" --depth "$DEPTH"

echo "[lpt2d] shipping new bundles"
"$ROOT/scripts/lpt2d-ship.sh"

echo "[lpt2d] done"
