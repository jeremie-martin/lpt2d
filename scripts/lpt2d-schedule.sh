#!/usr/bin/env bash
# Manage local lpt2d nightly render+ship timers and manual runs.
# Mirrors scripts/pendulum-schedule.sh from the double-pendulum repo.
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

SERVICES=(
    lpt2d-nightly.service
    lpt2d-workday.service
    lpt2d-manual.service
)

TIMERS=(
    lpt2d-nightly.timer
    lpt2d-workday.timer
)

MANUAL_SERVICE=lpt2d-manual.service

UNIT_FILES=(
    lpt2d-nightly.service
    lpt2d-nightly.timer
    lpt2d-workday.service
    lpt2d-workday.timer
    lpt2d-manual.service
)

usage() {
    cat <<'EOF'
Usage: scripts/lpt2d-schedule.sh <command>

Commands:
  start       Start a manual continuous render+ship (runs until paused)
  pause       Stop currently running jobs (scheduled timers stay enabled)
  stop        Stop running jobs AND disable both scheduled timers
  status      Show timer schedule + current unit status
  brief       Print a short status summary (for menus/scripts)
  enable      Enable and start both timers (nightly 01:00–07:00, workday Mon–Fri 09:30–17:30)
  disable     Disable both timers and stop running jobs
  install     Symlink all five unit files into ~/.config/systemd/user/
  deploy      Pull repo on $LPT2D_REMOTE, reload systemd, restart watcher.
              Pass --deps to also pip install/upgrade the publish runtime
              packages (loguru + google-* clients) into the venv.
EOF
}

cmd="${1:-status}"

case "$cmd" in
    start|start-now|run-now)
        systemctl --user daemon-reload
        systemctl --user start "$MANUAL_SERVICE"
        echo "Started manual render+ship. Use 'lpt2d-schedule.sh pause' to stop."
        ;;
    pause)
        systemctl --user stop "${SERVICES[@]}" 2>/dev/null || true
        echo "Paused current run(s). Next scheduled runs remain enabled."
        ;;
    stop)
        systemctl --user disable --now "${TIMERS[@]}" 2>/dev/null || true
        systemctl --user stop "${SERVICES[@]}" 2>/dev/null || true
        echo "Stopped current run(s) and disabled scheduled timers."
        ;;
    status)
        echo "Timers:"
        systemctl --user list-timers --all --no-pager \
            | grep -E 'lpt2d-(nightly|workday)|NEXT|LEFT|^$' || true
        echo
        echo "Units:"
        systemctl --user --no-pager --full status "${TIMERS[@]}" "${SERVICES[@]}" || true
        ;;
    brief)
        echo "Next timers:"
        systemctl --user list-timers --all --no-pager \
            | grep -E 'lpt2d-(nightly|workday)|NEXT|LEFT' || true
        echo
        echo "Running services:"
        systemctl --user list-units --type=service --state=running --no-pager \
            | grep -E 'lpt2d-(nightly|workday|manual)\.service' || echo "(none)"
        ;;
    enable)
        systemctl --user daemon-reload
        systemctl --user enable --now "${TIMERS[@]}"
        echo "Enabled timers."
        ;;
    disable)
        systemctl --user daemon-reload
        systemctl --user disable --now "${TIMERS[@]}" 2>/dev/null || true
        systemctl --user stop "${SERVICES[@]}" 2>/dev/null || true
        echo "Disabled timers and stopped active runs."
        ;;
    install)
        target="$HOME/.config/systemd/user"
        mkdir -p "$target"
        for unit in "${UNIT_FILES[@]}"; do
            ln -sf "$ROOT_DIR/systemd/user/$unit" "$target/$unit"
            echo "linked $unit"
        done
        systemctl --user daemon-reload
        echo "Now: scripts/lpt2d-schedule.sh enable"
        ;;
    deploy)
        # Pull the repo on the watcher host, reload systemd, restart the watcher.
        # Pass --deps as the second arg to also pip install (slow; only when
        # pyproject.toml or requirements changed).
        remote="${LPT2D_REMOTE:-holo@rpi.local}"
        venv_pip="\$HOME/lpt2d-publish/venv/bin/pip"
        deps_flag="${2:-}"
        echo "deploy: $remote"
        ssh "$remote" "
            set -e
            cd ~/lpt2d
            git fetch --quiet
            before=\$(git rev-parse HEAD)
            git pull --ff-only --quiet
            after=\$(git rev-parse HEAD)
            if [[ \$before == \$after ]]; then
                echo 'no new commits'
            else
                echo \"updated: \$before -> \$after\"
                git --no-pager log --oneline \"\$before..\$after\"
            fi
            if [[ '$deps_flag' == '--deps' ]]; then
                echo 'installing deps...'
                $venv_pip install --upgrade loguru google-auth-oauthlib google-api-python-client
            fi
            export XDG_RUNTIME_DIR=/run/user/\$(id -u)
            systemctl --user daemon-reload
            systemctl --user restart lpt2d-publish-watcher.service
            systemctl --user is-active lpt2d-publish-watcher.service
            journalctl --user -u lpt2d-publish-watcher.service -n 5 --no-pager
        "
        ;;
    -h|--help|help)
        usage
        ;;
    *)
        usage
        exit 1
        ;;
esac
