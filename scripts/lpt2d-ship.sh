#!/usr/bin/env bash
# Find every render bundle that has video.mp4 + params.json and no .shipped marker,
# refuse to ship bundles whose verdict.ok is false, rsync the rest into the VPS
# inbox, then mark .shipped locally so we never re-ship.
#
# Env knobs:
#   LPT2D_REMOTE         (default: holo@vps)
#   LPT2D_REMOTE_INBOX   (default: /home/holo/lpt2d-publish/inbox)
#   LPT2D_RENDERS        (default: $HOME/prog/lpt2d/renders)
set -euo pipefail

REMOTE="${LPT2D_REMOTE:-holo@vps}"
REMOTE_INBOX="${LPT2D_REMOTE_INBOX:-/home/holo/lpt2d-publish/inbox}"
RENDERS_ROOT="${LPT2D_RENDERS:-$HOME/prog/lpt2d/renders}"

if [[ ! -d "$RENDERS_ROOT" ]]; then
    echo "renders root does not exist: $RENDERS_ROOT" >&2
    exit 1
fi

# Discover bundles: directories at depth 2 under renders/ that hold both
# video.mp4 and params.json and have no .shipped marker. We prune any directory
# already containing .shipped so the scan doesn't grow unboundedly with all-time
# nightly history.
mapfile -t bundles < <(
    find "$RENDERS_ROOT" -mindepth 1 -maxdepth 3 -type d \
        \( -exec test -e {}/.shipped \; -prune \) -o \
        \( -mindepth 2 -type d -print \) 2>/dev/null \
        | while read -r d; do
              [[ -f "$d/video.mp4"   ]] || continue
              [[ -f "$d/params.json" ]] || continue
              printf '%s\n' "$d"
          done | sort
)

if [[ ${#bundles[@]} -eq 0 ]]; then
    echo "no pending bundles under $RENDERS_ROOT"
    exit 0
fi

shipped=0
skipped=0

for b in "${bundles[@]}"; do
    name="$(basename "$b")"

    # If verdict says the render failed the gate, skip and mark locally so
    # we don't re-evaluate it next run. Path is passed via argv (not interpolated
    # into the python source) so single-quotes / spaces in $b are safe.
    if [[ -f "$b/verdict.json" ]] \
       && ! python3 -c 'import json,sys; sys.exit(0 if json.load(open(sys.argv[1])).get("ok",True) else 1)' \
            "$b/verdict.json"; then
        echo "skip (verdict.ok=false): $b"
        touch "$b/.shipped"
        skipped=$((skipped + 1))
        continue
    fi

    # Ship into a sibling .tmp dir on the remote and rename atomically. This
    # prevents the watcher from picking up a half-transferred bundle whose
    # video.mp4 mtime keeps advancing past the SETTLE_SECONDS window during
    # a long rsync.
    tmp_remote="$REMOTE_INBOX/.staging_${name}.$$"
    final_remote="$REMOTE_INBOX/$name"
    echo "ship: $b -> $REMOTE:$final_remote/"
    rsync -a --partial --mkpath \
        --exclude=".shipped" \
        --exclude="video_published.mp4" \
        "$b/" "$REMOTE:$tmp_remote/"
    ssh "$REMOTE" "mv -- $(printf '%q' "$tmp_remote") $(printf '%q' "$final_remote")"
    touch "$b/.shipped"
    shipped=$((shipped + 1))
done

echo "done: shipped=$shipped skipped=$skipped"
