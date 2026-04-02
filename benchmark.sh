#!/usr/bin/env bash
set -euo pipefail

# ── Configuration ──────────────────────────────────────────────────────
BINARY="${BINARY:-./build/lpt2d}"
WIDTH="${WIDTH:-1920}"
HEIGHT="${HEIGHT:-1080}"
RAYS="${RAYS:-10000000}"
DEPTH="${DEPTH:-12}"
BATCH="${BATCH:-50000}"
SCENES=(three_spheres prism diamond lens fiber mirror_box ring double_slit)

# ── Setup ──────────────────────────────────────────────────────────────
if [[ ! -x "$BINARY" ]]; then
    echo "Binary not found: $BINARY — building..."
    cmake --build build -j"$(nproc)" --config Release
fi

COMMIT=$(git rev-parse --short HEAD 2>/dev/null || echo "unknown")
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
OUTDIR="benchmarks/${COMMIT}_${TIMESTAMP}"
mkdir -p "$OUTDIR"

echo "═══════════════════════════════════════════════════════════"
echo " lpt2d benchmark"
echo " commit:     $COMMIT"
echo " resolution: ${WIDTH}x${HEIGHT}"
echo " rays:       $RAYS"
echo " depth:      $DEPTH"
echo " output:     $OUTDIR/"
echo "═══════════════════════════════════════════════════════════"

# ── JSON header ────────────────────────────────────────────────────────
RESULTS="$OUTDIR/results.json"
cat > "$RESULTS" <<EOF
{
  "commit": "$(git rev-parse HEAD 2>/dev/null || echo unknown)",
  "commit_short": "$COMMIT",
  "date": "$(date -Iseconds)",
  "settings": {
    "width": $WIDTH,
    "height": $HEIGHT,
    "rays": $RAYS,
    "depth": $DEPTH,
    "batch": $BATCH
  },
  "scenes": [
EOF

FIRST=true
TOTAL_TIME=0

# ── Render each scene ──────────────────────────────────────────────────
for SCENE in "${SCENES[@]}"; do
    echo -n "  $SCENE ... "

    START=$(date +%s%N)
    $BINARY --headless \
        --scene "$SCENE" \
        --width "$WIDTH" \
        --height "$HEIGHT" \
        --rays "$RAYS" \
        --batch "$BATCH" \
        --depth "$DEPTH" \
        --output "$OUTDIR/${SCENE}.png" \
        2>/dev/null
    END=$(date +%s%N)

    ELAPSED_MS=$(( (END - START) / 1000000 ))
    ELAPSED_S=$(awk "BEGIN{printf \"%.2f\", $ELAPSED_MS/1000}")
    TOTAL_TIME=$((TOTAL_TIME + ELAPSED_MS))

    echo "${ELAPSED_S}s"

    # Append to JSON
    if [ "$FIRST" = true ]; then
        FIRST=false
    else
        echo "," >> "$RESULTS"
    fi
    cat >> "$RESULTS" <<EOF2
    {"name": "$SCENE", "time_ms": $ELAPSED_MS}
EOF2
done

TOTAL_S=$(awk "BEGIN{printf \"%.2f\", $TOTAL_TIME/1000}")

# ── Close JSON ─────────────────────────────────────────────────────────
cat >> "$RESULTS" <<EOF

  ],
  "total_time_ms": $TOTAL_TIME
}
EOF

echo "═══════════════════════════════════════════════════════════"
echo " Total: ${TOTAL_S}s"
echo " Results: $RESULTS"
echo "═══════════════════════════════════════════════════════════"

# ── Generate index.html for easy browsing ──────────────────────────────
HTML="$OUTDIR/index.html"
cat > "$HTML" <<'HTMLHEAD'
<!DOCTYPE html>
<html><head>
<meta charset="utf-8">
<title>lpt2d benchmark</title>
<style>
  body { background: #111; color: #eee; font-family: monospace; margin: 2em; }
  h1 { color: #fff; }
  .meta { color: #888; margin-bottom: 2em; }
  .grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(480px, 1fr)); gap: 1.5em; }
  .card { background: #1a1a1a; border-radius: 8px; overflow: hidden; }
  .card img { width: 100%; display: block; }
  .card .info { padding: 0.8em 1em; display: flex; justify-content: space-between; }
  .card .name { font-weight: bold; }
  .card .time { color: #888; }
</style>
</head><body>
HTMLHEAD

cat >> "$HTML" <<EOF
<h1>lpt2d benchmark</h1>
<div class="meta">
  Commit: $COMMIT &mdash; $(date '+%Y-%m-%d %H:%M') &mdash;
  ${WIDTH}&times;${HEIGHT} &mdash; $(printf "%'d" $RAYS) rays &mdash; ${TOTAL_S}s total
</div>
<div class="grid">
EOF

for SCENE in "${SCENES[@]}"; do
    TIME_MS=$(grep -o "\"name\": \"$SCENE\", \"time_ms\": [0-9]*" "$RESULTS" | grep -o '[0-9]*$')
    TIME_S=$(awk "BEGIN{printf \"%.2f\", $TIME_MS/1000}")
    cat >> "$HTML" <<EOF2
<div class="card">
  <img src="${SCENE}.png" alt="$SCENE">
  <div class="info"><span class="name">$SCENE</span><span class="time">${TIME_S}s</span></div>
</div>
EOF2
done

cat >> "$HTML" <<'HTMLFOOT'
</div>
</body></html>
HTMLFOOT

echo " Gallery:  $HTML"
