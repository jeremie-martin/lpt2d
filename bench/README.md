# Benchmarks

This directory holds the focused benchmark harness and the benchmark scene set.

## Main Entry Points

- [`bench.sh`](/home/holo/prog/lpt2d/bench/bench.sh)
  Optimization harness with fidelity comparison against a local baseline.
- [`manifest.json`](/home/holo/prog/lpt2d/bench/scenes/manifest.json)
  Benchmark scene list plus per-scene render settings.
- [OPTIMIZATION_LOG.md](/home/holo/prog/lpt2d/OPTIMIZATION_LOG.md)
  Accepted performance work and rejected experiments.

## Which Benchmark To Use

Use `benchmark.sh` from the repo root when you want a broad snapshot across the
built-in scene set.

Use `bench/bench.sh` when you are evaluating optimization work and need:

- repeatable timing over the fixed benchmark scene set
- image-fidelity comparison against a local baseline
- a verdict that combines performance and fidelity

## Common Commands

```bash
# Full optimization pass
bench/bench.sh

# Quick one-repeat check
bench/bench.sh --quick

# Capture the current working baseline locally
bench/bench.sh --capture-baseline

# Re-compare an existing benchmark directory
bench/bench.sh --compare-only benchmarks/<run-dir>
```

The local fidelity baseline lives under `bench/baseline/` and is intentionally
not part of git history.
