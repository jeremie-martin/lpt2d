#!/usr/bin/env bash
# Rofi menu over scripts/lpt2d-schedule.sh and the ship/server log helpers.
# Mirrors scripts/pendulum-rofi-menu.sh from the double-pendulum repo.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEDULE="$ROOT_DIR/scripts/lpt2d-schedule.sh"
SHIP="$ROOT_DIR/scripts/lpt2d-ship.sh"
REMOTE="${LPT2D_REMOTE:-holo@vps}"

if ! command -v rofi >/dev/null 2>&1; then
    echo "Error: rofi is not installed." >&2
    exit 1
fi

if [[ ! -x "$SCHEDULE" ]]; then
    echo "Error: missing helper script: $SCHEDULE" >&2
    exit 1
fi

notify() {
    local msg="$1"
    if command -v notify-send >/dev/null 2>&1; then
        notify-send "lpt2d" "$msg"
    fi
}

choice="$(
    printf '%s\n' \
        'Status' \
        'Start now (manual)' \
        'Ship pending bundles now' \
        'Deploy to server (git pull + restart)' \
        'Pause current run' \
        'Enable schedule timers' \
        'Disable all timers' \
        'Show recent local logs' \
        "Show recent server logs ($REMOTE)" \
    | rofi -dmenu -i -p 'lpt2d'
)" || true

[[ -n "${choice:-}" ]] || exit 0

run_action() {
    local output
    if output="$("$@" 2>&1)"; then
        return 0
    else
        rofi -e "Error: $output" || true
        return 1
    fi
}

case "$choice" in
    'Status')
        status="$("$SCHEDULE" brief 2>&1)" || true
        rofi -e "$status"
        ;;
    'Start now (manual)')
        run_action "$SCHEDULE" start && notify "Started manual render+ship"
        ;;
    'Ship pending bundles now')
        output="$("$SHIP" 2>&1)" || true
        rofi -e "$output"
        ;;
    'Deploy to server (git pull + restart)')
        output="$("$SCHEDULE" deploy 2>&1)" || true
        rofi -e "$output"
        ;;
    'Pause current run')
        run_action "$SCHEDULE" pause && notify "Paused current run"
        ;;
    'Enable schedule timers')
        run_action "$SCHEDULE" enable && notify "Enabled schedule timers"
        ;;
    'Disable all timers')
        run_action "$SCHEDULE" disable && notify "Disabled all timers"
        ;;
    'Show recent local logs')
        logs="$(journalctl --user \
            -u lpt2d-nightly.service \
            -u lpt2d-manual.service \
            -n 50 --no-pager 2>&1 || true)"
        rofi -e "$logs"
        ;;
    "Show recent server logs ($REMOTE)")
        logs="$(ssh "$REMOTE" \
            "journalctl --user -u lpt2d-publish-watcher.service -n 50 --no-pager" \
            2>&1 || true)"
        rofi -e "$logs"
        ;;
    *)
        ;;
esac
