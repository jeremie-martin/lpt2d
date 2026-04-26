#!/usr/bin/env bash
# Continuous render-and-ship loop.
#
# Render iris bundles one at a time and ship each to the VPS the moment it
# completes. The loop runs until SIGTERM (timer expiry or manual `systemctl
# stop`); the in-flight bundle interrupted by SIGTERM is rmtree'd at exit so
# we never leave half-rendered bundles on disk.
#
# Shipping is INLINE per bundle — there is no background sweep and no
# scanning of the global renders/ tree. Only bundles produced by THIS
# session get shipped. Old experimental directories are invisible to the
# pipeline.
#
# Three callers:
#   • lpt2d-nightly.service  (timer 01:00 daily, RuntimeMaxSec=6h → ends 07:00)
#   • lpt2d-workday.service  (timer Mon-Fri 09:30, RuntimeMaxSec=8h → ends 17:30)
#   • lpt2d-manual.service   (no timer, runs until manual `systemctl stop`)
#
# All three invoke this script and differ only in $LPT2D_WINDOW (which
# appears in the OUT dir name) and the service's RuntimeMaxSec.
#
# Render knobs (rays/fps/depth/crf/duration/branch) live in
# iris_demo.RESOLUTION_PRESETS; edit there once and every window inherits.
#
# Env knobs:
#   LPT2D_WINDOW          — nightly | workday | manual (default: manual)
#   LPT2D_RESOLUTION      — iris_demo preset (default: 720p)
#   LPT2D_REMOTE          — ssh target (default: holo@vps)
#   LPT2D_REMOTE_INBOX    — remote inbox dir (default: /home/holo/lpt2d-publish/inbox)
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
REMOTE="${LPT2D_REMOTE:-holo@vps}"
REMOTE_INBOX="${LPT2D_REMOTE_INBOX:-/home/holo/lpt2d-publish/inbox}"

TS_SESSION="$(date -u +%Y%m%dT%H%M%SZ)"
OUT="$ROOT/renders/lpt2d_iris_${WINDOW}_${TS_SESSION}_${RESOLUTION}"

# ── Per-bundle shipping ───────────────────────────────────────────────
# Ship one complete bundle: rsync to a staging dir on the remote, then
# atomic-rename into the inbox. Refuses to clobber an existing inbox bundle
# so collisions become loud failures rather than silent merge-into-dir
# (POSIX `mv src dst/` moves src INTO dst when dst is an existing dir —
# we explicitly guard against that).
ship_bundle() {
    local b="${1%/}"
    local name; name="$(basename "$b")"
    local tmp_remote="$REMOTE_INBOX/.staging_${name}.$$"
    local final_remote="$REMOTE_INBOX/$name"

    if [[ -f "$b/verdict.json" ]] \
       && ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok",True) else 1)' \
            "$b/verdict.json"; then
        echo "[lpt2d] skip (verdict.ok=false): $name"
        touch "$b/.shipped"
        return 0
    fi

    echo "[lpt2d] ship: $name"
    if ! rsync -a --partial --mkpath --timeout=60 \
           --exclude=".shipped" --exclude="video_published.mp4" \
           "$b/" "$REMOTE:$tmp_remote/"; then
        echo "[lpt2d] rsync FAILED for $name; bundle stays unshipped" >&2
        return 1
    fi

    if ! ssh -o ConnectTimeout=30 "$REMOTE" "
        if [[ -e $(printf '%q' "$final_remote") ]]; then
            rm -rf $(printf '%q' "$tmp_remote")
            echo '[lpt2d] remote target exists, refusing to clobber' >&2
            exit 1
        fi
        mv -- $(printf '%q' "$tmp_remote") $(printf '%q' "$final_remote")
    "; then
        echo "[lpt2d] remote rename FAILED for $name; bundle stays unshipped" >&2
        return 1
    fi

    touch "$b/.shipped"
}

# Ship every complete-but-unshipped bundle in this session's OUT.
# Normally there's exactly one (the bundle iris_demo just produced); the
# loop is only there to recover if a prior iteration's ship_bundle failed.
ship_session_bundles() {
    [[ -d "$OUT" ]] || return 0
    local b
    shopt -s nullglob
    for b in "$OUT"/*/; do
        [[ -f "$b/verdict.json" && ! -f "$b/.shipped" ]] || continue
        ship_bundle "${b%/}" || true
    done
    shopt -u nullglob
}

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
# EXIT trap: rmtree any partial bundle, then ship anything still un-shipped
# (typically empty since shipping is inline per iteration). rsync + ssh
# carry their own --timeout/-o ConnectTimeout so a hung remote can't stall
# past systemd's TimeoutStopSec=120.
trap 'cleanup_partials; ship_session_bundles || true' EXIT

echo "[lpt2d] continuous render: window=$WINDOW resolution=$RESOLUTION out=$OUT"

# ── Main loop ─────────────────────────────────────────────────────────
while [[ $STOP -eq 0 ]]; do
    cleanup_partials
    uv run python examples/python/families/iris_demo.py \
        --out "$OUT" -n 1 --resolution "$RESOLUTION" --no-index &
    RENDER_PID=$!
    wait "$RENDER_PID" || true
    RENDER_PID=
    ship_session_bundles
done

echo "[lpt2d] stop signal received"
