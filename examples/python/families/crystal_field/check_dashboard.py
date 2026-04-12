"""Generate a dashboard for the crystal_field acceptance constraints."""

from __future__ import annotations

import argparse
import html
import importlib
import json
from pathlib import Path
from typing import Any

from .sampling import OUTCOMES

CHECK = importlib.import_module(f"{__package__}.check")


ALL_OUTCOMES = (
    "glass",
    "black_diffuse",
    "gray_diffuse",
    "colored_diffuse",
    "brushed_metal",
)

GATING_METRICS = {
    "moving_radius_min",
    "moving_radius_max",
    "ambient_radius_min",
    "ambient_radius_max",
    "moving_to_ambient_radius_ratio",
    "near_black_fraction",
    "mean",
    "shadow_floor",
    "contrast_spread",
    "shadow_fraction",
    "mean_saturation",
}


def _pct(value: float) -> str:
    return f"{100.0 * value:.1f}%"


def _num(value: float) -> str:
    if abs(value) < 1.0:
        return f"{value:.3f}"
    return f"{value:.1f}"


def _constraint(
    section: str,
    metric: str,
    pass_rule: str,
    rejection: str,
    why: str,
) -> dict[str, str]:
    return {
        "section": section,
        "metric": metric,
        "pass_rule": pass_rule,
        "rejection": rejection,
        "why": why,
    }


def _check_order() -> list[dict[str, str]]:
    return [
        _constraint("Presence", "moving_count", "> 0", "no moving lights", "The scene needs at least one analyzed moving point light."),
        _constraint("Presence", "ambient_count", "> 0", "no ambient lights", "Ambient lights provide the reference circle size."),
        _constraint("Moving radius", "moving_radius_min", f">= {_num(CHECK.MIN_MOVING_RADIUS_RATIO)}", "moving_radius_min", "Every moving light must be large enough to be visible."),
        _constraint("Moving radius", "moving_radius_max", f"<= {_num(CHECK.MAX_MOVING_RADIUS_RATIO)}", "moving_radius_max", "No moving light should dominate the frame."),
        _constraint("Ambient radius", "ambient_radius_min", f">= {_num(CHECK.MIN_AMBIENT_RADIUS_RATIO)}", "ambient_radius_min", "Ambient reference circles cannot collapse to pinpoints."),
        _constraint("Ambient radius", "ambient_radius_max", f"<= {_num(CHECK.MAX_AMBIENT_RADIUS_RATIO)}", "ambient_radius_max", "Ambient reference circles cannot become too broad."),
        _constraint("Balance", "moving_to_ambient_radius_ratio", f">= {_num(CHECK.MIN_RADIUS_RATIO)}", "moving_to_ambient_radius_ratio", "Moving lights should read larger than ambient lights."),
        _constraint("Balance", "moving_to_ambient_radius_ratio", f"<= {_num(CHECK.MAX_RADIUS_RATIO)}", "moving_to_ambient_radius_ratio", "Moving lights should not be wildly larger than ambient lights."),
        _constraint("Tone", "near_black_fraction", f"<= {_pct(CHECK.MAX_NEAR_BLACK_FRACTION)}", "near_black", "Rejects frames with too much crushed black."),
        _constraint("Tone", "mean", f">= {_num(CHECK.MIN_MEAN_LUMINANCE)}", "brightness", "Rejects frames that are too dark."),
        _constraint("Tone", "mean", "outcome dependent", "brightness", "Rejects frames that are too bright; glass has a stricter ceiling."),
        _constraint("Tone", "shadow_floor", f"<= {_num(CHECK.MAX_SHADOW_FLOOR)}", "shadows", "Rejects raised shadows that wash out the image."),
        _constraint("Tone", "contrast_spread", f">= {_num(CHECK.MIN_CONTRAST_SPREAD)}", "contrast_spread", "Requires enough p10 to p90 luminance spread."),
        _constraint("Tone", "shadow_fraction", "outcome dependent", "shadow_pixels", "Rejects too many dark pixels; black diffuse gets a looser ceiling."),
        _constraint("Color", "mean_saturation", f"< {_num(CHECK.MAX_MEAN_SATURATION)}", "saturation", "Rejects over-saturated frames."),
    ]


def _global_constraints() -> list[dict[str, str]]:
    return [
        _constraint("Light presence", "moving_count", "> 0", "no moving lights", "Structural requirement."),
        _constraint("Light presence", "ambient_count", "> 0", "no ambient lights", "Structural requirement."),
        _constraint("Moving radius", "moving_radius_min", f">= {_num(CHECK.MIN_MOVING_RADIUS_RATIO)}", "moving_radius_min", "All moving lights must clear this lower bound."),
        _constraint("Moving radius", "moving_radius_max", f"<= {_num(CHECK.MAX_MOVING_RADIUS_RATIO)}", "moving_radius_max", "All moving lights must stay under this upper bound."),
        _constraint("Ambient radius", "ambient_radius_min", f">= {_num(CHECK.MIN_AMBIENT_RADIUS_RATIO)}", "ambient_radius_min", "All ambient lights must clear this lower bound."),
        _constraint("Ambient radius", "ambient_radius_max", f"<= {_num(CHECK.MAX_AMBIENT_RADIUS_RATIO)}", "ambient_radius_max", "All ambient lights must stay under this upper bound."),
        _constraint("Radius balance", "moving_to_ambient_radius_ratio", f"{_num(CHECK.MIN_RADIUS_RATIO)} to {_num(CHECK.MAX_RADIUS_RATIO)}", "moving_to_ambient_radius_ratio", "Uses moving radius mean divided by ambient radius mean."),
        _constraint("Tone", "near_black_fraction", f"<= {_pct(CHECK.MAX_NEAR_BLACK_FRACTION)}", "near_black", "Global crushed-black ceiling."),
        _constraint("Tone", "mean", f">= {_num(CHECK.MIN_MEAN_LUMINANCE)}", "brightness", "Global lower brightness bound."),
        _constraint("Tone", "mean", f"<= {_num(CHECK.MAX_MEAN_LUMINANCE)} by default", "brightness", "Upper brightness bound unless overridden by outcome."),
        _constraint("Tone", "shadow_floor", f"<= {_num(CHECK.MAX_SHADOW_FLOOR)}", "shadows", "Global shadow-floor ceiling."),
        _constraint("Tone", "contrast_spread", f">= {_num(CHECK.MIN_CONTRAST_SPREAD)}", "contrast_spread", "Global contrast requirement."),
        _constraint("Tone", "shadow_fraction", f"<= {_pct(CHECK.MAX_SHADOW_FRACTION)} by default", "shadow_pixels", "Upper shadow-pixel fraction unless overridden by outcome."),
        _constraint("Color", "mean_saturation", f"< {_num(CHECK.MAX_MEAN_SATURATION)}", "saturation", "Strictly less than the threshold."),
    ]


def _overrides() -> list[dict[str, str]]:
    return [
        {
            "outcome": "glass",
            "metric": "mean",
            "default_rule": f"<= {_num(CHECK.MAX_MEAN_LUMINANCE)}",
            "effective_rule": f"<= {_num(CHECK.GLASS_MAX_MEAN_LUMINANCE)}",
            "effect": "stricter brightness ceiling",
        },
        {
            "outcome": "black_diffuse",
            "metric": "shadow_fraction",
            "default_rule": f"<= {_pct(CHECK.MAX_SHADOW_FRACTION)}",
            "effective_rule": f"<= {_pct(CHECK.BLACK_DIFFUSE_MAX_SHADOW_FRACTION)}",
            "effect": "looser shadow-pixel ceiling",
        },
    ]


def _effective_outcomes() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    active = set(OUTCOMES)
    for outcome in ALL_OUTCOMES:
        max_mean = (
            CHECK.GLASS_MAX_MEAN_LUMINANCE
            if outcome == "glass"
            else CHECK.MAX_MEAN_LUMINANCE
        )
        max_shadow = (
            CHECK.BLACK_DIFFUSE_MAX_SHADOW_FRACTION
            if outcome == "black_diffuse"
            else CHECK.MAX_SHADOW_FRACTION
        )
        override_notes = []
        if outcome == "glass":
            override_notes.append("mean ceiling")
        if outcome == "black_diffuse":
            override_notes.append("shadow fraction")
        rows.append(
            {
                "outcome": outcome,
                "active": "yes" if outcome in active else "no",
                "moving_radius": f"{_num(CHECK.MIN_MOVING_RADIUS_RATIO)} to {_num(CHECK.MAX_MOVING_RADIUS_RATIO)}",
                "ambient_radius": f"{_num(CHECK.MIN_AMBIENT_RADIUS_RATIO)} to {_num(CHECK.MAX_AMBIENT_RADIUS_RATIO)}",
                "radius_ratio": f"{_num(CHECK.MIN_RADIUS_RATIO)} to {_num(CHECK.MAX_RADIUS_RATIO)}",
                "mean": f"{_num(CHECK.MIN_MEAN_LUMINANCE)} to {_num(max_mean)}",
                "near_black": f"<= {_pct(CHECK.MAX_NEAR_BLACK_FRACTION)}",
                "shadow_floor": f"<= {_num(CHECK.MAX_SHADOW_FLOOR)}",
                "contrast": f">= {_num(CHECK.MIN_CONTRAST_SPREAD)}",
                "shadow_fraction": f"<= {_pct(max_shadow)}",
                "saturation": f"< {_num(CHECK.MAX_MEAN_SATURATION)}",
                "overrides": ", ".join(override_notes) if override_notes else "none",
            }
        )
    return rows


def constraint_model() -> dict[str, Any]:
    recorded_not_gating = sorted(set(CHECK.METRIC_KEYS) - GATING_METRICS)
    return {
        "probe": {
            "width": CHECK.PROBE_W,
            "height": CHECK.PROBE_H,
            "fps": CHECK.PROBE_FPS,
            "rays": CHECK.PROBE_RAYS,
            "frame_selection": "frame where moving lights are furthest from objects",
            "first_failure": True,
        },
        "active_outcomes": list(OUTCOMES),
        "all_outcomes": list(ALL_OUTCOMES),
        "check_order": _check_order(),
        "global_constraints": _global_constraints(),
        "overrides": _overrides(),
        "effective_outcomes": _effective_outcomes(),
        "recorded_not_gating": recorded_not_gating,
    }


def _esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def _table(headers: list[str], rows: list[dict[str, str]], keys: list[str]) -> str:
    parts = ["<div class=\"tablewrap\"><table><thead><tr>"]
    parts.extend(f"<th>{_esc(header)}</th>" for header in headers)
    parts.append("</tr></thead><tbody>")
    for row in rows:
        parts.append("<tr>")
        parts.extend(f"<td>{_esc(row[key])}</td>" for key in keys)
        parts.append("</tr>")
    parts.append("</tbody></table></div>")
    return "".join(parts)


def _pipeline(rows: list[dict[str, str]]) -> str:
    parts = ["<div class=\"pipeline\">"]
    for idx, row in enumerate(rows, start=1):
        parts.append(
            "<article class=\"gate\">"
            f"<div class=\"gate-top\"><span>{idx:02d}</span><strong>{_esc(row['metric'])}</strong></div>"
            f"<div class=\"rule\">{_esc(row['pass_rule'])}</div>"
            f"<div class=\"meta\">{_esc(row['section'])} / first reason: <code>{_esc(row['rejection'])}</code></div>"
            f"<p>{_esc(row['why'])}</p>"
            "</article>"
        )
    parts.append("</div>")
    return "".join(parts)


def _overview_cards(model: dict[str, Any]) -> str:
    probe = model["probe"]
    cards = [
        ("Probe", f"{probe['width']}x{probe['height']}", f"{probe['rays']:,} rays"),
        ("Frame", f"{probe['fps']} fps", probe["frame_selection"]),
        ("Active Outcomes", str(len(model["active_outcomes"])), ", ".join(model["active_outcomes"])),
        ("Semantics", "first failure", "The reported reason is the first failed gate, not every violation."),
    ]
    parts = ["<div class=\"cards\">"]
    for label, value, detail in cards:
        parts.append(
            "<article class=\"card\">"
            f"<div class=\"label\">{_esc(label)}</div>"
            f"<div class=\"value\">{_esc(value)}</div>"
            f"<p>{_esc(detail)}</p>"
            "</article>"
        )
    parts.append("</div>")
    return "".join(parts)


def _metric_pills(metrics: list[str]) -> str:
    return "<div class=\"pills\">" + "".join(f"<span>{_esc(metric)}</span>" for metric in metrics) + "</div>"


def render_html(model: dict[str, Any]) -> str:
    global_table = _table(
        ["Section", "Metric", "Pass Rule", "First Rejection", "Intent"],
        model["global_constraints"],
        ["section", "metric", "pass_rule", "rejection", "why"],
    )
    override_table = _table(
        ["Outcome", "Metric", "Default Rule", "Effective Rule", "Effect"],
        model["overrides"],
        ["outcome", "metric", "default_rule", "effective_rule", "effect"],
    )
    outcome_table = _table(
        [
            "Outcome",
            "Active",
            "Moving Radius",
            "Ambient Radius",
            "Moving/Ambient",
            "Mean",
            "Near Black",
            "Shadow Floor",
            "Contrast",
            "Shadow Pixels",
            "Saturation",
            "Overrides",
        ],
        model["effective_outcomes"],
        [
            "outcome",
            "active",
            "moving_radius",
            "ambient_radius",
            "radius_ratio",
            "mean",
            "near_black",
            "shadow_floor",
            "contrast",
            "shadow_fraction",
            "saturation",
            "overrides",
        ],
    )
    pipeline = _pipeline(model["check_order"])
    overview = _overview_cards(model)
    metrics = _metric_pills(model["recorded_not_gating"])

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Crystal Field Check Constraints</title>
<style>
* {{ box-sizing: border-box; }}
:root {{
  color-scheme: dark;
  --bg: #101110;
  --band: #151715;
  --panel: #1b1d1a;
  --ink: #f1f4ef;
  --muted: #a7aea5;
  --line: #343a34;
  --accent: #5bd6a2;
  --accent2: #69c7c0;
  --warn: #f0c94a;
  --bad: #ff7b72;
}}
body {{
  margin: 0;
  background: var(--bg);
  color: var(--ink);
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, sans-serif;
}}
main {{ max-width: 1440px; margin: 0 auto; padding: 24px; }}
header {{ padding: 10px 0 18px; }}
h1 {{ margin: 0 0 8px; font-size: 36px; line-height: 1.05; }}
h2 {{ margin: 34px 0 10px; font-size: 23px; }}
p {{ line-height: 1.45; }}
code {{ color: var(--accent); }}
.muted {{ color: var(--muted); }}
.note {{
  border-left: 3px solid var(--accent);
  background: var(--band);
  padding: 10px 12px;
  margin: 12px 0;
}}
.cards {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
  gap: 12px;
  margin: 18px 0 6px;
}}
.card, .gate {{
  background: var(--panel);
  border: 1px solid var(--line);
  border-radius: 8px;
  padding: 13px;
}}
.label, .meta {{ color: var(--muted); font-size: 12px; }}
.value {{ font-size: 25px; font-weight: 750; margin: 4px 0 2px; }}
.pipeline {{
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(245px, 1fr));
  gap: 10px;
}}
.gate-top {{ display: flex; gap: 8px; align-items: center; }}
.gate-top span {{
  display: inline-grid;
  place-items: center;
  width: 30px;
  height: 30px;
  border-radius: 8px;
  background: #24352d;
  color: var(--accent);
  font-weight: 800;
  font-size: 12px;
}}
.rule {{
  margin: 10px 0 6px;
  font-size: 20px;
  font-weight: 800;
  color: var(--accent2);
}}
.tablewrap {{
  overflow: auto;
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
}}
table {{ border-collapse: collapse; min-width: 980px; width: 100%; }}
th, td {{
  border-bottom: 1px solid var(--line);
  padding: 8px 9px;
  text-align: left;
  vertical-align: top;
}}
th {{
  position: sticky;
  top: 0;
  background: #20231f;
  color: #dfe6dc;
  z-index: 1;
}}
td {{ color: #e8ece6; }}
tr:hover td {{ background: #181b18; }}
.pills {{ display: flex; flex-wrap: wrap; gap: 7px; }}
.pills span {{
  border: 1px solid var(--line);
  border-radius: 8px;
  background: var(--panel);
  color: #dce4da;
  padding: 5px 7px;
  font-size: 13px;
}}
.twocol {{
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
  gap: 18px;
}}
@media (max-width: 900px) {{
  main {{ padding: 15px; }}
  h1 {{ font-size: 29px; }}
  .twocol {{ grid-template-columns: 1fr; }}
  table {{ min-width: 760px; }}
}}
</style>
</head>
<body>
<main>
<header>
  <h1>Crystal Field Check Constraints</h1>
  <p class="muted">Live acceptance thresholds from <code>examples/python/families/crystal_field/check.py</code>.</p>
  <p class="note">The gate is ordered. A rejected row reports the first failed condition, so later violated constraints may be hidden by the first failure reason.</p>
</header>

{overview}

<section>
  <h2>Gate Order</h2>
  {pipeline}
</section>

<section class="twocol">
  <div>
    <h2>Global Thresholds</h2>
    {global_table}
  </div>
  <div>
    <h2>Outcome Overrides</h2>
    {override_table}
    <p class="muted">Only these two thresholds are overloaded by outcome. Everything else is global.</p>
  </div>
</section>

<section>
  <h2>Effective Constraints By Outcome</h2>
  {outcome_table}
</section>

<section>
  <h2>Recorded But Not Gating</h2>
  <p class="muted">These metrics are exported for analysis dashboards but are not direct pass/fail gates.</p>
  {metrics}
</section>
</main>
</body>
</html>
"""


def _output_paths(out: str) -> tuple[Path, Path]:
    path = Path(out)
    if path.suffix == ".html":
        return path, path.with_name("constraints.json")
    return path / "index.html", path / "constraints.json"


def run_check_dashboard(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description="Write a crystal_field check-constraint dashboard")
    parser.add_argument(
        "--out",
        default="renders/families/crystal_field/check_constraints",
        help="Output directory, or an explicit .html path",
    )
    args = parser.parse_args(argv)

    html_path, json_path = _output_paths(args.out)
    html_path.parent.mkdir(parents=True, exist_ok=True)

    model = constraint_model()
    html_path.write_text(render_html(model), encoding="utf-8")
    json_path.write_text(json.dumps(model, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Dashboard: {html_path}")
    print(f"Data: {json_path}")


if __name__ == "__main__":
    run_check_dashboard()
