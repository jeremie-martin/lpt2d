#!/usr/bin/env bash
set -euo pipefail

# Compare two benchmark runs side by side.
# Usage: ./benchmark-compare.sh [run1_dir] [run2_dir]
#        ./benchmark-compare.sh          # compares two most recent runs

BENCH_DIR="benchmarks"

if [[ $# -ge 2 ]]; then
    DIR_A="$1"
    DIR_B="$2"
elif [[ $# -eq 1 ]]; then
    DIR_A="$1"
    DIR_B=$(ls -td "$BENCH_DIR"/*/ 2>/dev/null | head -1)
else
    DIRS=($(ls -td "$BENCH_DIR"/*/ 2>/dev/null))
    if [[ ${#DIRS[@]} -lt 2 ]]; then
        echo "Need at least 2 benchmark runs to compare. Found: ${#DIRS[@]}"
        echo "Run ./benchmark.sh to generate benchmarks."
        exit 1
    fi
    DIR_A="${DIRS[1]}"  # older
    DIR_B="${DIRS[0]}"  # newer
fi

# Strip trailing slashes so path splitting works correctly in HTML generation
DIR_A="${DIR_A%/}"
DIR_B="${DIR_B%/}"

for D in "$DIR_A" "$DIR_B"; do
    if [[ ! -f "$D/results.json" ]]; then
        echo "Not a benchmark directory (missing results.json): $D"
        exit 1
    fi
done

COMMIT_A=$(python3 -c "import json; print(json.load(open('$DIR_A/results.json'))['commit_short'])")
COMMIT_B=$(python3 -c "import json; print(json.load(open('$DIR_B/results.json'))['commit_short'])")
DATE_A=$(python3 -c "import json; print(json.load(open('$DIR_A/results.json'))['date'][:10])")
DATE_B=$(python3 -c "import json; print(json.load(open('$DIR_B/results.json'))['date'][:10])")

echo "═══════════════════════════════════════════════════════════"
echo " Comparing: $COMMIT_A ($DATE_A) → $COMMIT_B ($DATE_B)"
echo "═══════════════════════════════════════════════════════════"
printf "  %-20s %10s %10s %10s\n" "Scene" "Before" "After" "Change"
echo "  ─────────────────── ────────── ────────── ──────────"

SCENES=$(python3 -c "
import json
a = {s['name']: s['time_ms'] for s in json.load(open('$DIR_A/results.json'))['scenes']}
b = {s['name']: s['time_ms'] for s in json.load(open('$DIR_B/results.json'))['scenes']}
for name in a:
    if name in b:
        ta, tb = a[name], b[name]
        pct = (tb - ta) / ta * 100 if ta > 0 else 0
        sign = '+' if pct > 0 else ''
        print(f'  {name:<20s} {ta/1000:>9.2f}s {tb/1000:>9.2f}s {sign}{pct:>8.1f}%')
ta = sum(s['time_ms'] for s in json.load(open('$DIR_A/results.json'))['scenes'])
tb = sum(s['time_ms'] for s in json.load(open('$DIR_B/results.json'))['scenes'])
pct = (tb - ta) / ta * 100 if ta > 0 else 0
sign = '+' if pct > 0 else ''
print(f'  {\"TOTAL\":<20s} {ta/1000:>9.2f}s {tb/1000:>9.2f}s {sign}{pct:>8.1f}%')
")
echo "$SCENES"
echo "═══════════════════════════════════════════════════════════"

# Generate comparison HTML
HTML="$BENCH_DIR/compare_${COMMIT_A}_vs_${COMMIT_B}.html"
python3 -c "
import json

a_data = json.load(open('$DIR_A/results.json'))
b_data = json.load(open('$DIR_B/results.json'))
a_scenes = {s['name']: s for s in a_data['scenes']}
b_scenes = {s['name']: s for s in b_data['scenes']}

html = '''<!DOCTYPE html>
<html><head><meta charset=\"utf-8\"><title>lpt2d compare</title>
<style>
  body { background: #111; color: #eee; font-family: monospace; margin: 2em; }
  h1, h2 { color: #fff; }
  .meta { color: #888; margin-bottom: 1em; }
  .scene { margin-bottom: 2em; }
  .pair { display: flex; gap: 4px; }
  .pair img { width: 50%; }
  .labels { display: flex; gap: 4px; margin-top: 0.3em; }
  .labels span { width: 50%; text-align: center; color: #888; }
  .faster { color: #4a4; } .slower { color: #a44; }
</style></head><body>
<h1>lpt2d: $COMMIT_A vs $COMMIT_B</h1>
<div class=\"meta\">$DATE_A → $DATE_B</div>'''

for name in a_scenes:
    if name not in b_scenes: continue
    ta = a_scenes[name]['time_ms']
    tb = b_scenes[name]['time_ms']
    pct = (tb - ta) / ta * 100 if ta > 0 else 0
    cls = 'faster' if pct < -1 else ('slower' if pct > 1 else '')
    sign = '+' if pct > 0 else ''
    html += f'''
<div class=\"scene\">
  <h2>{name} <span class=\"{cls}\">({sign}{pct:.1f}%)</span></h2>
  <div class=\"pair\">
    <img src=\"{'/'.join('$DIR_A'.split('/')[-1:])}/{name}.png\">
    <img src=\"{'/'.join('$DIR_B'.split('/')[-1:])}/{name}.png\">
  </div>
  <div class=\"labels\">
    <span>$COMMIT_A ({ta/1000:.2f}s)</span>
    <span>$COMMIT_B ({tb/1000:.2f}s)</span>
  </div>
</div>'''

html += '</body></html>'
open('$HTML', 'w').write(html)
"

echo " Comparison: $HTML"
