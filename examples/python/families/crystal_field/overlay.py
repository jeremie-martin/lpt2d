"""Draw metric overlays onto rendered catalog images.

The catalog exists to give the user a visual-vs-numeric baseline — you
look at each image and want to know *which numbers the filters saw when
deciding whether to accept it*.  This module draws a small text block on
the bottom-left of each PNG showing the measurements that ``check.py``
computed for that frame.

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
    ("mean", "mean", "%.2f"),
    ("contrast_spread", "spread", "%.2f"),
    ("highlight_peak", "peak", "%.2f"),
    ("clipped_channel_fraction", "clipped", "%.1f%%"),
    ("mean_saturation", "sat", "%.2f"),
    ("colorful_seconds", "color", "%.1fs"),
    ("moving_radius_ratio", "moving_r", "%.1f%%"),
    ("ambient_radius_ratio", "ambient_r", "%.1f%%"),
    ("radius_ratio", "ratio", "%.2f"),
    ("transition_width_ratio", "edge", "%.1f%%"),
    ("peak_contrast", "contrast", "%.3f"),
    ("confidence", "conf", "%.2f"),
    ("exposure", "exp", "%.2f"),
    ("gamma", "gam", "%.2f"),
    ("white_point", "wp", "%.2f"),
)


def _format_metric(label: str, key: str, value: float, fmt: str) -> str:
    percent_keys = {
        "clipped_channel_fraction",
        "moving_radius_ratio",
        "ambient_radius_ratio",
        "transition_width_ratio",
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
