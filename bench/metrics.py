#!/usr/bin/env python3
"""Compare a benchmark run against a baseline: image fidelity + performance.

Usage:
    python3 bench/metrics.py <run_dir> <baseline_dir>

Reads:
    <run_dir>/<scene>.png, <baseline_dir>/<scene>.png
    <run_dir>/results.json, <baseline_dir>/results.json

Writes:
    <run_dir>/verdict.json

Exit code: 0 = pass (all scenes PASS or WARN), 1 = fidelity fail
"""

import hashlib
import json
import math
import sys
from pathlib import Path
from statistics import median, stdev, mean

import numpy as np
from PIL import Image

# ── Fidelity thresholds ──────────────────────────────────────────────────

PASS_PSNR = 45.0
PASS_SSIM = 0.995
PASS_MAX_DIFF = 10

WARN_PSNR = 40.0
WARN_SSIM = 0.98


# ── Image metrics ────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def load_image(path: Path) -> np.ndarray:
    """Load PNG as uint8 RGB array (H, W, 3)."""
    img = Image.open(path).convert("RGB")
    return np.asarray(img, dtype=np.uint8)


def compute_mse(a: np.ndarray, b: np.ndarray) -> dict:
    diff = a.astype(np.float64) - b.astype(np.float64)
    mse_ch = np.mean(diff ** 2, axis=(0, 1))  # per-channel
    return {
        "r": float(mse_ch[0]),
        "g": float(mse_ch[1]),
        "b": float(mse_ch[2]),
        "combined": float(np.mean(mse_ch)),
    }


def compute_psnr(mse: float) -> float:
    if mse < 1e-10:
        return float("inf")
    return 10.0 * math.log10(255.0 ** 2 / mse)


def box_filter(img: np.ndarray, win: int) -> np.ndarray:
    """Fast O(n) box filter via cumulative sum. Input: (H, W) float64."""
    pad = win // 2
    padded = np.pad(img, pad, mode="reflect")
    # cumsum along rows
    cs = np.cumsum(padded, axis=0)
    cs = cs[win:] - cs[:-win]
    # cumsum along cols
    cs = np.cumsum(cs, axis=1)
    cs = cs[:, win:] - cs[:, :-win]
    return cs / (win * win)


def compute_ssim(a: np.ndarray, b: np.ndarray, win: int = 11) -> float:
    """SSIM (Wang 2004) with box filter, computed per-channel then averaged."""
    C1 = (0.01 * 255) ** 2
    C2 = (0.03 * 255) ** 2

    af = a.astype(np.float64)
    bf = b.astype(np.float64)

    ssim_channels = []
    for ch in range(af.shape[2]):
        ac = af[:, :, ch]
        bc = bf[:, :, ch]

        mu_a = box_filter(ac, win)
        mu_b = box_filter(bc, win)

        sigma_a2 = box_filter(ac * ac, win) - mu_a * mu_a
        sigma_b2 = box_filter(bc * bc, win) - mu_b * mu_b
        sigma_ab = box_filter(ac * bc, win) - mu_a * mu_b

        num = (2 * mu_a * mu_b + C1) * (2 * sigma_ab + C2)
        den = (mu_a ** 2 + mu_b ** 2 + C1) * (sigma_a2 + sigma_b2 + C2)

        ssim_map = num / den
        ssim_channels.append(float(np.mean(ssim_map)))

    return float(np.mean(ssim_channels))


def compute_histogram_overlap(a: np.ndarray, b: np.ndarray) -> dict:
    """Per-channel histogram intersection coefficient (1.0 = identical)."""
    result = {}
    for ch, name in enumerate(["r", "g", "b"]):
        ha, _ = np.histogram(a[:, :, ch], bins=256, range=(0, 256))
        hb, _ = np.histogram(b[:, :, ch], bins=256, range=(0, 256))
        ha = ha.astype(np.float64)
        hb = hb.astype(np.float64)
        total = max(ha.sum(), hb.sum(), 1.0)
        result[name] = float(np.minimum(ha, hb).sum() / total)
    return result


def compute_channel_stats(img: np.ndarray) -> dict:
    result = {}
    for ch, name in enumerate(["r", "g", "b"]):
        c = img[:, :, ch].astype(np.float64)
        result[name] = {"mean": float(np.mean(c)), "std": float(np.std(c))}
    return result


def compare_images(run_path: Path, baseline_path: Path) -> dict:
    """Full fidelity comparison between two images."""
    # Fast path: byte-identical files
    run_hash = sha256_file(run_path)
    base_hash = sha256_file(baseline_path)

    if run_hash == base_hash:
        return {"verdict": "PASS", "byte_identical": True}

    # Load and compare
    a = load_image(baseline_path)
    b = load_image(run_path)

    if a.shape != b.shape:
        return {
            "verdict": "FAIL",
            "byte_identical": False,
            "error": f"Shape mismatch: baseline {a.shape} vs run {b.shape}",
        }

    mse = compute_mse(a, b)
    psnr = compute_psnr(mse["combined"])
    ssim = compute_ssim(a, b)

    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    max_abs_diff = int(np.max(diff))
    pct_changed = float(np.mean(np.any(diff > 1, axis=2)) * 100)

    hist_overlap = compute_histogram_overlap(a, b)

    # Classify
    if psnr >= PASS_PSNR and ssim >= PASS_SSIM and max_abs_diff <= PASS_MAX_DIFF:
        verdict = "PASS"
    elif psnr >= WARN_PSNR and ssim >= WARN_SSIM:
        verdict = "WARN"
    else:
        verdict = "FAIL"

    return {
        "verdict": verdict,
        "byte_identical": False,
        "psnr": round(psnr, 2) if psnr != float("inf") else "inf",
        "ssim": round(ssim, 6),
        "mse": {k: round(v, 4) for k, v in mse.items()},
        "max_abs_diff": max_abs_diff,
        "pct_pixels_changed": round(pct_changed, 3),
        "histogram_overlap": {k: round(v, 4) for k, v in hist_overlap.items()},
    }


# ── Performance metrics ──────────────────────────────────────────────────

def cv(times: list[float]) -> float:
    """Coefficient of variation (%)."""
    if len(times) < 2 or mean(times) < 1e-6:
        return 0.0
    return stdev(times) / mean(times) * 100


def classify_speedup(baseline_times: list[float], current_times: list[float]) -> str:
    if not baseline_times or not current_times:
        return "no_data"
    if max(current_times) < min(baseline_times):
        return "confirmed"
    if min(current_times) > max(baseline_times):
        return "confirmed_regression"
    bmed = median(baseline_times)
    cmed = median(current_times)
    if bmed < 1e-6:
        return "no_data"
    change = (bmed - cmed) / bmed
    cur_cv = cv(current_times)
    if change > 0.05 and cur_cv < 10:
        return "likely"
    if change < -0.05 and cur_cv < 10:
        return "regression"
    return "noise"


def compare_performance(run_results: dict, baseline_results: dict) -> dict:
    """Compare timing data between run and baseline."""
    run_scenes = run_results.get("scenes", {})
    base_scenes = baseline_results.get("scenes", {})
    rays = run_results.get("rays", 10000000)

    scene_perf = {}
    total_base = 0.0
    total_current = 0.0

    for name in run_scenes:
        rt = run_scenes[name].get("times_ms", [])
        bt = base_scenes.get(name, {}).get("times_ms", [])

        rmed = median(rt) if rt else 0
        bmed = median(bt) if bt else 0

        total_base += bmed
        total_current += rmed

        scene_perf[name] = {
            "baseline_times_ms": bt,
            "current_times_ms": rt,
            "baseline_median_ms": round(bmed, 1),
            "current_median_ms": round(rmed, 1),
            "speedup": round(bmed / rmed, 4) if rmed > 0 else 0,
            "confidence": classify_speedup(bt, rt),
            "current_cv_pct": round(cv(rt), 2),
            "rays_per_sec": int(rays / (rmed / 1000)) if rmed > 0 else 0,
        }

    total_speedup = total_base / total_current if total_current > 0 else 0

    # Overall confidence: compute per-repeat total times across all scenes
    scene_names = list(run_scenes.keys())
    n_base = min((len(base_scenes.get(n, {}).get("times_ms", [])) for n in scene_names), default=0)
    n_curr = min((len(run_scenes[n].get("times_ms", [])) for n in scene_names), default=0)

    all_base_totals = [
        sum(base_scenes.get(n, {}).get("times_ms", [0] * n_base)[i] for n in scene_names)
        for i in range(n_base)
    ]
    all_curr_totals = [
        sum(run_scenes[n].get("times_ms", [0] * n_curr)[i] for n in scene_names)
        for i in range(n_curr)
    ]

    total_confidence = classify_speedup(
        [t for t in all_base_totals if t > 0],
        [t for t in all_curr_totals if t > 0],
    ) if all_base_totals and all_curr_totals else "no_data"

    return {
        "total_baseline_ms": round(total_base, 1),
        "total_current_ms": round(total_current, 1),
        "total_speedup": round(total_speedup, 4),
        "total_confidence": total_confidence,
        "scenes": scene_perf,
    }


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    if len(sys.argv) != 3:
        print(f"Usage: {sys.argv[0]} <run_dir> <baseline_dir>", file=sys.stderr)
        sys.exit(2)

    run_dir = Path(sys.argv[1])
    baseline_dir = Path(sys.argv[2])

    if not run_dir.is_dir():
        print(f"Run directory not found: {run_dir}", file=sys.stderr)
        sys.exit(2)
    if not baseline_dir.is_dir():
        print(f"Baseline directory not found: {baseline_dir}", file=sys.stderr)
        sys.exit(3)

    # Discover scenes from run directory (all PNGs that aren't scratch)
    run_pngs = sorted(p for p in run_dir.glob("*.png") if not p.name.startswith("."))
    scene_names = [p.stem for p in run_pngs]

    if not scene_names:
        print(f"No PNG files found in {run_dir}", file=sys.stderr)
        sys.exit(2)

    # Fidelity comparison
    fidelity_results = {}
    any_fail = False

    for name in scene_names:
        run_img = run_dir / f"{name}.png"
        base_img = baseline_dir / f"{name}.png"

        if not base_img.exists():
            fidelity_results[name] = {"verdict": "FAIL", "error": "Missing baseline image"}
            any_fail = True
            continue

        result = compare_images(run_img, base_img)
        fidelity_results[name] = result
        if result["verdict"] == "FAIL":
            any_fail = True

    # Performance comparison
    perf = {}
    run_results_path = run_dir / "results.json"
    base_results_path = baseline_dir / "results.json"

    if run_results_path.exists() and base_results_path.exists():
        run_results = json.loads(run_results_path.read_text())
        base_results = json.loads(base_results_path.read_text())
        perf = compare_performance(run_results, base_results)

    # Assemble verdict
    verdict = {
        "overall": "FAIL" if any_fail else "PASS",
        "fidelity_pass": not any_fail,
        "performance": {
            "total_baseline_ms": perf.get("total_baseline_ms", 0),
            "total_current_ms": perf.get("total_current_ms", 0),
            "total_speedup": perf.get("total_speedup", 0),
            "total_confidence": perf.get("total_confidence", "no_data"),
        },
        "scenes": {},
    }

    for name in scene_names:
        scene_entry = {
            "fidelity": fidelity_results.get(name, {}),
        }
        scene_perf = perf.get("scenes", {}).get(name)
        if scene_perf:
            scene_entry["performance"] = scene_perf
        verdict["scenes"][name] = scene_entry

    # Write verdict
    verdict_path = run_dir / "verdict.json"
    verdict_path.write_text(json.dumps(verdict, indent=2) + "\n")

    # Print summary
    print(f"{'='*60}")
    print(f" Verdict: {verdict['overall']}")
    print(f"{'='*60}")

    for name in scene_names:
        fid = fidelity_results.get(name, {})
        fv = fid.get("verdict", "?")
        ident = " (identical)" if fid.get("byte_identical") else ""
        psnr_str = ""
        if not fid.get("byte_identical") and "psnr" in fid:
            psnr_str = f" PSNR={fid['psnr']}dB SSIM={fid.get('ssim', '?')}"

        perf_str = ""
        sp = perf.get("scenes", {}).get(name)
        if sp:
            perf_str = f" | {sp['current_median_ms']:.0f}ms"
            if sp["speedup"] > 0:
                perf_str += f" ({sp['speedup']:.3f}x {sp['confidence']})"

        print(f"  {name:30s} {fv:4s}{ident}{psnr_str}{perf_str}")

    if perf:
        print(f"{'─'*60}")
        p = verdict["performance"]
        print(f"  {'TOTAL':30s}      | {p['total_current_ms']:.0f}ms"
              f" ({p['total_speedup']:.3f}x {p['total_confidence']})")

    print(f"{'='*60}")
    print(f" Written: {verdict_path}")

    sys.exit(1 if any_fail else 0)


if __name__ == "__main__":
    main()
