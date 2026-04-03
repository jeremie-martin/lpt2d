#!/usr/bin/env bash
set -euo pipefail

# ── Optimization benchmark harness for lpt2d ─────────────────────────────
#
# Usage:
#   bench/bench.sh                       Full: build + render + compare
#   bench/bench.sh --quick               1 repeat, no warm-up
#   bench/bench.sh --capture-baseline    Render + save as baseline
#   bench/bench.sh --compare-only <dir>  Re-compare existing run
#
# Environment overrides:
#   REPEATS=5  bench/bench.sh            Custom repeat count
#   BINARY=... bench/bench.sh            Custom binary path
#
# Exit codes: 0=pass, 1=fidelity fail, 2=build/render error, 3=no baseline

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BINARY="${BINARY:-$PROJECT_DIR/build/lpt2d-cli}"
SCENE_DIR="$SCRIPT_DIR/scenes"
BASELINE_DIR="$SCRIPT_DIR/baseline"
MANIFEST="$SCENE_DIR/manifest.json"
REPEATS="${REPEATS:-3}"
MAX_RUNS=20  # auto-clean old runs

MODE="full"
COMPARE_DIR=""

# ── Argument parsing ─────────────────────────────────────────────────────

for arg in "$@"; do
    case "$arg" in
        --quick)
            MODE="quick"
            REPEATS=1
            ;;
        --capture-baseline)
            MODE="capture-baseline"
            ;;
        --compare-only)
            MODE="compare-only"
            ;;
        *)
            if [[ "$MODE" == "compare-only" && -z "$COMPARE_DIR" ]]; then
                COMPARE_DIR="$arg"
            fi
            ;;
    esac
done

if [[ "$MODE" == "compare-only" && -z "$COMPARE_DIR" ]]; then
    echo "Error: --compare-only requires a directory argument" >&2
    exit 2
fi

# ── Read manifest ────────────────────────────────────────────────────────

if [[ ! -f "$MANIFEST" ]]; then
    echo "Error: manifest not found: $MANIFEST" >&2
    exit 2
fi

# Parse manifest into arrays via Python
eval "$(python3 -c "
import json, sys
m = json.load(open('$MANIFEST'))
d = m['defaults']
names = []
for s in m['scenes']:
    merged = {**d, **s}
    names.append(merged['name'])
# Print bash arrays
print('SCENE_NAMES=(' + ' '.join(names) + ')')
print('SCENE_COUNT=' + str(len(names)))
" 2>/dev/null)"

# Build per-scene config arrays (with overrides)
declare -A SCENE_WIDTH SCENE_HEIGHT SCENE_RAYS SCENE_BATCH SCENE_DEPTH
declare -A SCENE_EXPOSURE SCENE_CONTRAST SCENE_GAMMA SCENE_TONEMAP

while IFS=$'\t' read -r name width height rays batch depth exposure contrast gamma tonemap; do
    SCENE_WIDTH[$name]=$width
    SCENE_HEIGHT[$name]=$height
    SCENE_RAYS[$name]=$rays
    SCENE_BATCH[$name]=$batch
    SCENE_DEPTH[$name]=$depth
    SCENE_EXPOSURE[$name]=$exposure
    SCENE_CONTRAST[$name]=$contrast
    SCENE_GAMMA[$name]=$gamma
    SCENE_TONEMAP[$name]=$tonemap
done < <(python3 -c "
import json
m = json.load(open('$MANIFEST'))
d = m['defaults']
for s in m['scenes']:
    mg = {**d, **s}
    print(mg['name'], mg['width'], mg['height'], mg['rays'], mg['batch'],
          mg['depth'], mg['exposure'], mg['contrast'], mg['gamma'], mg['tonemap'],
          sep='\t')
" 2>/dev/null)

# ── Helper functions ─────────────────────────────────────────────────────

render_scene() {
    local name="$1" output="$2"
    "$BINARY" \
        --scene "$SCENE_DIR/${name}.json" \
        --width "${SCENE_WIDTH[$name]}" \
        --height "${SCENE_HEIGHT[$name]}" \
        --rays "${SCENE_RAYS[$name]}" \
        --batch "${SCENE_BATCH[$name]}" \
        --depth "${SCENE_DEPTH[$name]}" \
        --exposure "${SCENE_EXPOSURE[$name]}" \
        --contrast "${SCENE_CONTRAST[$name]}" \
        --gamma "${SCENE_GAMMA[$name]}" \
        --tonemap "${SCENE_TONEMAP[$name]}" \
        --output "$output" \
        2>/dev/null
}

timed_render() {
    local name="$1" output="$2"
    local start end
    start=$(date +%s%N)
    render_scene "$name" "$output"
    end=$(date +%s%N)
    echo $(( (end - start) / 1000000 ))
}

cleanup_old_runs() {
    local bench_dir="$PROJECT_DIR/benchmarks"
    [[ -d "$bench_dir" ]] || return 0
    local count
    count=$(find "$bench_dir" -maxdepth 1 -mindepth 1 -type d | wc -l)
    if (( count > MAX_RUNS )); then
        find "$bench_dir" -maxdepth 1 -mindepth 1 -type d -printf '%T@ %p\n' \
            | sort -n \
            | head -n $(( count - MAX_RUNS )) \
            | cut -d' ' -f2- \
            | while read -r d; do rm -rf "$d"; done
    fi
}

# ── Compare-only mode ────────────────────────────────────────────────────

if [[ "$MODE" == "compare-only" ]]; then
    if [[ ! -d "$BASELINE_DIR" ]]; then
        echo "Error: no baseline found at $BASELINE_DIR" >&2
        exit 3
    fi
    python3 "$SCRIPT_DIR/metrics.py" "$COMPARE_DIR" "$BASELINE_DIR"
    exit $?
fi

# ── Build ────────────────────────────────────────────────────────────────

echo "Building Release..."
cmake -S "$PROJECT_DIR" -B "$PROJECT_DIR/build" -DCMAKE_BUILD_TYPE=Release >/dev/null 2>&1
cmake --build "$PROJECT_DIR/build" -j"$(nproc)" 2>&1 | tail -1

if [[ ! -x "$BINARY" ]]; then
    echo "Error: binary not found after build: $BINARY" >&2
    exit 2
fi

# ── Create run directory ─────────────────────────────────────────────────

COMMIT=$(git -C "$PROJECT_DIR" rev-parse --short HEAD 2>/dev/null || echo "unknown")
TIMESTAMP=$(date +%Y%m%d-%H%M%S)
RUN_DIR="$PROJECT_DIR/benchmarks/${COMMIT}_bench_${TIMESTAMP}"
mkdir -p "$RUN_DIR"

echo "═══════════════════════════════════════════════════════════"
echo " lpt2d optimization benchmark"
echo " commit:  $COMMIT"
echo " mode:    $MODE (repeats=$REPEATS)"
echo " scenes:  $SCENE_COUNT"
echo " output:  $RUN_DIR/"
echo "═══════════════════════════════════════════════════════════"

# ── Warm-up ──────────────────────────────────────────────────────────────

if [[ "$MODE" != "quick" ]]; then
    echo -n "  warm-up (${SCENE_NAMES[0]}) ... "
    render_scene "${SCENE_NAMES[0]}" "$RUN_DIR/.scratch.png"
    echo "done"
fi

# ── Render each scene ────────────────────────────────────────────────────

declare -A SCENE_TIMES  # name -> comma-separated ms values

for name in "${SCENE_NAMES[@]}"; do
    echo -n "  $name ... "

    # Deterministic image render
    render_scene "$name" "$RUN_DIR/${name}.png"

    # Timed repeats
    times=()
    for (( i=1; i<=REPEATS; i++ )); do
        t=$(timed_render "$name" "$RUN_DIR/.scratch.png")
        times+=("$t")
    done

    SCENE_TIMES[$name]=$(IFS=,; echo "${times[*]}")

    # Print median
    median_ms=$(python3 -c "
from statistics import median
times = [${SCENE_TIMES[$name]}]
print(f'{median(times):.0f}')
")
    echo "${median_ms}ms (${REPEATS} runs: ${SCENE_TIMES[$name]})"
done

# Clean scratch
rm -f "$RUN_DIR/.scratch.png"

# ── Write results.json ───────────────────────────────────────────────────

python3 -c "
import json
from datetime import datetime

scenes = {}
$(for name in "${SCENE_NAMES[@]}"; do
    echo "scenes['$name'] = {'times_ms': [${SCENE_TIMES[$name]}]}"
done)

# Compute total from medians
from statistics import median
total = sum(median(s['times_ms']) for s in scenes.values())

results = {
    'commit': '$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)',
    'commit_short': '$COMMIT',
    'date': datetime.now().isoformat(),
    'rays': ${SCENE_RAYS[${SCENE_NAMES[0]}]},
    'repeats': $REPEATS,
    'scenes': scenes,
    'total_median_ms': round(total, 1),
}

with open('$RUN_DIR/results.json', 'w') as f:
    json.dump(results, f, indent=2)
    f.write('\n')
" 2>/dev/null

# ── Capture baseline mode ────────────────────────────────────────────────

if [[ "$MODE" == "capture-baseline" ]]; then
    echo ""
    echo "Capturing baseline..."
    rm -rf "$BASELINE_DIR"
    mkdir -p "$BASELINE_DIR"

    # Copy images
    for name in "${SCENE_NAMES[@]}"; do
        cp "$RUN_DIR/${name}.png" "$BASELINE_DIR/"
    done

    # Copy results
    cp "$RUN_DIR/results.json" "$BASELINE_DIR/"

    # Write manifest with checksums
    python3 -c "
import json, hashlib
from datetime import datetime
from pathlib import Path

baseline = Path('$BASELINE_DIR')
checksums = {}
for p in sorted(baseline.glob('*.png')):
    h = hashlib.sha256(p.read_bytes()).hexdigest()
    checksums[p.name] = f'sha256:{h}'

manifest = {
    'commit': '$(git -C "$PROJECT_DIR" rev-parse HEAD 2>/dev/null || echo unknown)',
    'commit_short': '$COMMIT',
    'date': datetime.now().isoformat(),
    'checksums': checksums,
}

with open(baseline / 'manifest.json', 'w') as f:
    json.dump(manifest, f, indent=2)
    f.write('\n')
" 2>/dev/null

    echo "═══════════════════════════════════════════════════════════"
    echo " Baseline saved to: $BASELINE_DIR/"
    echo " Images: $(ls "$BASELINE_DIR"/*.png 2>/dev/null | wc -l)"
    echo " This baseline is local-only and ignored by git."
    echo "═══════════════════════════════════════════════════════════"
    exit 0
fi

# ── Compare to baseline ──────────────────────────────────────────────────

if [[ ! -d "$BASELINE_DIR" ]]; then
    echo ""
    echo "Warning: no baseline found. Run with --capture-baseline first." >&2
    echo "Results saved to: $RUN_DIR/"
    exit 3
fi

python3 "$SCRIPT_DIR/metrics.py" "$RUN_DIR" "$BASELINE_DIR"
VERDICT_EXIT=$?

# ── Cleanup old runs ─────────────────────────────────────────────────────

cleanup_old_runs

exit $VERDICT_EXIT
