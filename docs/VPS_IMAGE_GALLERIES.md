# VPS Image Galleries

This is the lightweight workflow for publishing render-review images when the
user explicitly asks for it. Do not upload images on your own initiative.

## Rules

- Use the SSH host alias `vps`. Do not hard-code the public IP address in repo
  docs, scripts, commits, or generated durable files.
- Create a new web page directory for each requested upload. Prefer descriptive
  names such as `lpt2d_light_radius_gpu_1080p_10m_YYYYMMDD`.
- Publish web images as JPEG by default. Full-resolution PNG render outputs are
  useful locally, but they are too large for quick phone review and repeated VPS
  uploads.
- Keep the page phone-friendly: visible thumbnails, direct metrics links, and a
  simple click-to-open viewer with previous/next navigation.
- Keep generated image directories out of git unless the user explicitly asks
  to track a specific artifact.

## Served Root

The current image server on `vps` serves:

```text
/tmp/crystal_field_stills
```

Upload a gallery with:

```bash
rsync -az --delete renders/<gallery>_web/ \
  vps:/tmp/crystal_field_stills/<gallery>/
```

Then verify the page through the HTTP URL supplied by the user for that server.

## Light-Radius Characterization

The light-radius characterization script can build the JPEG gallery directly:

```bash
PYTHONPATH=build python -m examples.python.families.light_radius_characterization \
  --out renders/lpt2d_light_radius_gpu_1080p_10m_YYYYMMDD \
  --web-out renders/lpt2d_light_radius_gpu_1080p_10m_YYYYMMDD_web \
  --width 1920 --height 1080 --rays 10000000 --batch 100000 --depth 12
```

If the PNG render directory already exists, rebuild only the web gallery:

```bash
PYTHONPATH=build python -m examples.python.families.light_radius_characterization \
  --web-only \
  --out renders/lpt2d_light_radius_gpu_1080p_10m_YYYYMMDD \
  --web-out renders/lpt2d_light_radius_gpu_1080p_10m_YYYYMMDD_web
```

