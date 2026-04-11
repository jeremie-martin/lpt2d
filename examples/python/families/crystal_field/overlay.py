"""Draw metric overlays onto rendered catalog images.

The catalog exists to give the user a visual-vs-numeric baseline: the
render, the exported shot JSON, and this overlay all use the same frame
selected by ``check.py`` for probe analysis.  The numbers are the core
analysis fields exposed through the Python binding, plus the moving vs
ambient light-radius aggregates used by the crystal_field rejection policy.

The overlay is applied to the PNG in place (loaded, modified, saved).
It is deliberately kept simple: one helper, no abstractions.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Display order and format spec for each metric.  Only keys listed here are
# rendered; extras in the metrics dict are silently dropped.
_METRIC_ORDER: tuple[tuple[str, str, str], ...] = (
    ("analysis_time", "analysis_time", "%.2fs"),
    ("mean", "brightness", "%.1f"),
    ("median", "median", "%.0f"),
    ("percentile_10", "p10", "%.0f"),
    ("percentile_90", "p90", "%.0f"),
    ("shadow_floor", "shadows", "%.0f"),
    ("contrast_std", "contrast_std", "%.1f"),
    ("contrast_spread", "contrast_spread", "%.1f"),
    ("histogram_entropy_normalized", "luma_entropy", "%.3f"),
    ("near_black_fraction", "near_black", "%.1f%%"),
    ("near_white_fraction", "near_white", "%.1f%%"),
    ("shadow_fraction", "shadow_px", "%.1f%%"),
    ("midtone_fraction", "midtone_px", "%.1f%%"),
    ("highlight_fraction", "highlight_px", "%.1f%%"),
    ("clipped_channel_fraction", "clipped_ch", "%.1f%%"),
    ("mean_saturation", "saturation", "%.3f"),
    ("saturation_coverage", "sat_coverage", "%.3f"),
    ("colored_fraction", "colored_px", "%.1f%%"),
    ("moving_radius_min", "moving_min", "%.1f%%"),
    ("moving_radius_mean", "moving_mean", "%.1f%%"),
    ("moving_radius_max", "moving_max", "%.1f%%"),
    ("ambient_radius_min", "ambient_min", "%.1f%%"),
    ("ambient_radius_mean", "ambient_mean", "%.1f%%"),
    ("ambient_radius_max", "ambient_max", "%.1f%%"),
    ("moving_to_ambient_radius_ratio", "moving_to_ambient", "%.2f"),
)


def _format_metric(label: str, key: str, value: float, fmt: str) -> str:
    percent_keys = {
        "near_black_fraction",
        "near_white_fraction",
        "shadow_fraction",
        "midtone_fraction",
        "highlight_fraction",
        "clipped_channel_fraction",
        "colored_fraction",
        "moving_radius_min",
        "moving_radius_mean",
        "moving_radius_max",
        "ambient_radius_min",
        "ambient_radius_mean",
        "ambient_radius_max",
    }
    scaled = value * 100.0 if key in percent_keys else value
    return f"{label}: {fmt % scaled}"


@lru_cache(maxsize=8)
def _load_mono_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    """Best-effort monospace font; falls back to Pillow's default bitmap."""
    for candidate in (
        "/usr/share/fonts/TTF/DejaVuSansMono.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
        "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
        "/Library/Fonts/Menlo.ttc",
    ):
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def draw_metrics_overlay(
    png_path: Path | str,
    metrics: dict[str, float],
    *,
    font_size: int = 18,
    padding: int = 10,
    margin: int = 16,
) -> None:
    """Draw a translucent text block of metrics onto an existing PNG.

    Parameters
    ----------
    png_path
        Path to the PNG to modify in place.
    metrics
        Flat dict of metric name → value.  Only keys listed in
        ``_METRIC_ORDER`` are rendered; extras are dropped.
    font_size
        Pixel size for the text.  Tuned for 1920×1080 catalog images.
    padding
        Pixels between the text and the background rectangle's edge.
    margin
        Pixels between the background rectangle and the image edge.
    """
    path = Path(png_path)
    image = Image.open(path).convert("RGBA")

    lines: list[str] = []
    for key, label, fmt in _METRIC_ORDER:
        if key in metrics:
            lines.append(_format_metric(label, key, metrics[key], fmt))

    if not lines:
        return

    font = _load_mono_font(font_size)

    # Measure each line so we can size the background rectangle.
    ascent_test = ImageDraw.Draw(image)
    line_widths: list[int] = []
    line_heights: list[int] = []
    for line in lines:
        bbox = ascent_test.textbbox((0, 0), line, font=font)
        line_widths.append(int(bbox[2] - bbox[0]))
        line_heights.append(int(bbox[3] - bbox[1]))

    line_height = max(line_heights) + 2
    box_w = max(line_widths) + 2 * padding
    box_h = line_height * len(lines) + 2 * padding

    # Position bottom-left with margin.
    _img_w, img_h = image.size
    x0 = margin
    y0 = img_h - margin - box_h

    # Draw semi-transparent background on an RGBA overlay, then composite.
    overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
    overlay_draw = ImageDraw.Draw(overlay)
    overlay_draw.rounded_rectangle(
        [(x0, y0), (x0 + box_w, y0 + box_h)],
        radius=6,
        fill=(0, 0, 0, 180),
    )
    image = Image.alpha_composite(image, overlay)

    # Text on the composited image.
    draw = ImageDraw.Draw(image)
    tx = x0 + padding
    ty = y0 + padding
    for line in lines:
        draw.text((tx, ty), line, font=font, fill=(255, 255, 255, 255))
        ty += line_height

    image.convert("RGB").save(path)
