#!/usr/bin/env bash
set -euo pipefail

SEED="${SEED:-0}"
N="${N:-1000000}"
OUT="${OUT:-renders/families/crystal_field/studies/measured_noglass_1m_seed${SEED}.jsonl}"
ANALYSIS_OUT="${ANALYSIS_OUT:-${OUT%.jsonl}_analysis}"
PROGRESS_EVERY="${PROGRESS_EVERY:-5000}"

python -m examples.python.families.crystal_field study measure \
  --out "${OUT}" \
  --n "${N}" \
  --seed "${SEED}" \
  --progress-every "${PROGRESS_EVERY}" \
  --fsync-every 1

python -m examples.python.families.crystal_field study analyze \
  --in "${OUT}" \
  --out "${ANALYSIS_OUT}"
