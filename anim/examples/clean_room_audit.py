"""Audit clean-room scenes for bounds and base-exposure brightness metrics."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from anim.examples._clean_room_registry import SCENES
from anim.examples._clean_room_shared import ANALYSIS_MODE, audit_room_bounds, evaluate_exposure


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__ or "Audit clean-room scene metrics.")
    parser.add_argument(
        "--family",
        action="append",
        dest="families",
        help="limit the audit to one or more scene families",
    )
    parser.add_argument(
        "--match",
        action="append",
        dest="matches",
        help="limit the audit to scenes whose names contain the substring",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="limit the number of audited scenes after filtering",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("renders/clean_room/library_audit.json"),
        help="output JSON path",
    )
    args = parser.parse_args()

    selected = list(SCENES)
    if args.families:
        wanted = set(args.families)
        selected = [spec for spec in selected if (spec.family or "misc") in wanted]
    if args.matches:
        lowered = [pattern.lower() for pattern in args.matches]
        selected = [spec for spec in selected if any(pattern in spec.name.lower() for pattern in lowered)]
    if args.limit is not None:
        selected = selected[: args.limit]
    if not selected:
        raise SystemExit("no scenes matched the requested filters")

    args.out.parent.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, object]] = []
    for index, spec in enumerate(selected, start=1):
        print(f"[{index:03d}/{len(selected):03d}] {spec.name}")
        audit = audit_room_bounds(spec, duration=spec.duration)
        summary = evaluate_exposure(spec, spec.base_exposure, ANALYSIS_MODE)
        results.append(
            {
                "name": spec.name,
                "family": spec.family or "misc",
                "description": spec.description,
                "base_exposure": spec.base_exposure,
                "room_fit": audit.fits_room,
                "max_overrun": audit.max_overrun,
                "bounds": audit.bounds,
                "score": summary.score,
                "metrics": summary.to_dict(),
            }
        )

    worst = sorted(results, key=lambda item: float(item["score"]), reverse=True)
    payload = {
        "scene_count": len(results),
        "analysis_mode": {
            "width": ANALYSIS_MODE.canvas.width,
            "height": ANALYSIS_MODE.canvas.height,
            "rays": ANALYSIS_MODE.trace.rays,
            "batch": ANALYSIS_MODE.trace.batch,
            "depth": ANALYSIS_MODE.trace.depth,
            "fps": ANALYSIS_MODE.fps,
        },
        "families": sorted({str(item["family"]) for item in results}),
        "worst_by_score": [
            {
                "name": item["name"],
                "family": item["family"],
                "score": item["score"],
                "lit_p90": item["metrics"]["lit_p90"],
                "clipped_pct": item["metrics"]["clipped_pct"],
                "room_fit": item["room_fit"],
            }
            for item in worst[:40]
        ],
        "results": results,
    }
    with args.out.open("w") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
