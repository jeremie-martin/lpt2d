#!/usr/bin/env bash
# Continuous render-and-ship loop.
#
# Renders iris variants one at a time and ships completed bundles to the VPS
# in the background. Runs until SIGTERM (timer expiry or manual `systemctl
# stop`). The current in-flight bundle, if interrupted by SIGTERM, has its
# directory `rmtree`'d on exit so we never leave half-rendered bundles on
# disk — the contract is "verdict.json present ⇒ render complete".
#
# Three callers:
#   • lpt2d-nightly.service  (timer 01:00, RuntimeMaxSec=6h → ends 07:00)
#   • lpt2d-workday.service  (timer Mon-Fri 09:30, RuntimeMaxSec=8h → ends 17:30)
#   • lpt2d-manual.service   (no timer, runs until manual `systemctl stop`)
#
# All three invoke this script. They differ only in the LPT2D_WINDOW env var
# (which appears in the OUT directory name) and the systemd RuntimeMaxSec.
#
# Render knobs (rays/fps/depth/crf/duration/branch) live in
# iris_demo.RESOLUTION_PRESETS — edit there once and every window inherits.
#
# Env knobs:
#   LPT2D_WINDOW          — nightly | workday | manual (default: manual)
#   LPT2D_RESOLUTION      — iris_demo preset (default: 720p)
#   LPT2D_SHIP_INTERVAL   — seconds between ship sweeps (default: 30)
#   LPT2D_REMOTE          — see lpt2d-ship.sh
#   LPT2D_REMOTE_INBOX    — see lpt2d-ship.sh
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

WINDOW="${LPT2D_WINDOW:-manual}"
RESOLUTION="${LPT2D_RESOLUTION:-720p}"
SHIP_INTERVAL="${LPT2D_SHIP_INTERVAL:-30}"

TS_SESSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/renders/lpt2d_iris_${WINDOW}_${TS_SESSION}_${RESOLUTION}"

# ── Partial-bundle cleanup ────────────────────────────────────────────
# A bundle is "complete" iff verdict.json exists (iris_batch writes it last,
# after the ffmpeg encode returns). Anything with params.json but no
# verdict.json was interrupted — rmtree it.
cleanup_partials() {
    [[ -d "$OUT" ]] || return 0
    local d
    shopt -s nullglob
    for d in "$OUT"/*/; do
        if [[ -f "$d/params.json" && ! -f "$d/verdict.json" ]]; then
            echo "[lpt2d] removing partial bundle: $d"
            rm -rf "$d"
        fi
    done
    shopt -u nullglob
}

# ── Background ship loop ──────────────────────────────────────────────
ship_periodically() {
    while sleep "$SHIP_INTERVAL"; do
        "$ROOT/scripts/lpt2d-ship.sh" || true
    done
}

ship_periodically &
SHIP_PID=$!

# ── Stop handling ─────────────────────────────────────────────────────
# SIGTERM/SIGINT: set STOP and forward to the in-flight render. Under systemd
# the default KillMode=control-group already SIGTERMs every pid in the unit's
# cgroup (bash + python + ffmpeg), so this `kill -TERM` is mainly for the
# non-systemd "operator runs the script directly" case.
STOP=0
RENDER_PID=
on_signal() {
    STOP=1
    [[ -n "$RENDER_PID" ]] && kill -TERM "$RENDER_PID" 2>/dev/null || true
}
trap on_signal INT TERM
# Final ship is bounded so a backed-up inbox can't blow past systemd's
# TimeoutStopSec=120 and trigger a SIGKILL mid-rsync. Anything left over
# stays locally-`.shipped`-marker-less and ships on the next run.
# 100s = unit's TimeoutStopSec (120s) − ~20s slack for the preceding steps.
trap '
    kill "$SHIP_PID" 2>/dev/null || true
    wait "$SHIP_PID" 2>/dev/null || true
    cleanup_partials
    timeout 100 "$ROOT/scripts/lpt2d-ship.sh" || true
' EXIT

echo "[lpt2d] continuous render: window=$WINDOW resolution=$RESOLUTION out=$OUT (ship every ${SHIP_INTERVAL}s)"

# Defensive: clean up any debris from a prior run that died past the trap.
cleanup_partials

# ── Main loop ─────────────────────────────────────────────────────────
while [[ $STOP -eq 0 ]]; do
    # Remove any partial bundle from a previous failed iteration before
    # starting the next render.
    cleanup_partials

    uv run python examples/python/families/iris_demo.py \
        --out "$OUT" -n 1 --resolution "$RESOLUTION" --no-index &
    RENDER_PID=$!
    wait "$RENDER_PID" || true
    RENDER_PID=
done

echo "[lpt2d] stop signal received; final ship pass runs in EXIT trap"
