#!/usr/bin/env bash
set -euo pipefail

SEED="${SEED:-0}"
N="${N:-50000}"
OUT="${OUT:-renders/families/crystal_field/studies/measured_noglass_50k_seed${SEED}.jsonl}"
ANALYSIS_OUT="${ANALYSIS_OUT:-${OUT%.jsonl}_analysis}"

python -m examples.python.families.crystal_field study measure \
  --out "${OUT}" \
  --n "${N}" \
  --seed "${SEED}"

python -m examples.python.families.crystal_field study analyze \
  --in "${OUT}" \
  --out "${ANALYSIS_OUT}"
