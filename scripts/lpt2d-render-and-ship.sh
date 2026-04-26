#!/usr/bin/env bash
# Daily entry point: render an iris batch and ship completed bundles to the VPS.
# Wrapped in flock so concurrent timer firings don't double-render. While the
# renderer is working we run a background ship loop that picks up each bundle
# as soon as iris_batch writes its verdict.json (the "render complete"
# sentinel), so the VPS watcher can start uploading well before the full batch
# has finished — same shape as dp's per-video scp on the C++ side.
#
# Env knobs:
#   LPT2D_NIGHTLY_N         — bundles per nightly batch (default: 12)
#   LPT2D_NIGHTLY_RES       — width:height (default: 1080:1920)
#   LPT2D_NIGHTLY_FPS       — fps (default: 24)
#   LPT2D_NIGHTLY_DURATION  — seconds per video (default: 60)
#   LPT2D_NIGHTLY_RAYS      — rays per pixel (default: 1000000)
#   LPT2D_NIGHTLY_DEPTH     — bounce depth (default: 10)
#   LPT2D_SHIP_INTERVAL     — seconds between ship sweeps while rendering (default: 30)
#   LPT2D_REMOTE            — see lpt2d-ship.sh
#   LPT2D_REMOTE_INBOX      — see lpt2d-ship.sh
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

SHIP_INTERVAL="${LPT2D_SHIP_INTERVAL:-30}"

# Background ship loop: while iris_batch is rendering, sweep renders/ every
# SHIP_INTERVAL seconds and rsync any bundle whose verdict.json has been
# written. iris_batch writes verdict.json LAST, so no half-encoded video gets
# shipped.
ship_periodically() {
    while sleep "$SHIP_INTERVAL"; do
        "$ROOT/scripts/lpt2d-ship.sh" || true
    done
}
ship_periodically &
SHIP_PID=$!
trap 'kill "$SHIP_PID" 2>/dev/null || true; wait "$SHIP_PID" 2>/dev/null || true' EXIT INT TERM

echo "[lpt2d] nightly render: out=$OUT n=$N res=${WIDTH}x${HEIGHT}@${FPS} dur=${DURATION}s (ship every ${SHIP_INTERVAL}s)"
uv run python examples/python/families/iris_batch.py \
    --out "$OUT" \
    -n "$N" \
    --width "$WIDTH" --height "$HEIGHT" \
    --fps "$FPS" --duration "$DURATION" \
    --rays "$RAYS" --depth "$DEPTH"

# Render finished — stop the loop and run one final ship to catch the last
# bundle (whose verdict.json may have landed after the last sweep tick).
kill "$SHIP_PID" 2>/dev/null || true
wait "$SHIP_PID" 2>/dev/null || true
trap - EXIT INT TERM

echo "[lpt2d] final ship pass"
"$ROOT/scripts/lpt2d-ship.sh"

echo "[lpt2d] done"
