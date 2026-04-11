# Glossary

Canonical terminology for lpt2d. Every term listed here should be used
consistently across C++, Python, JSON, shaders, GUI, and documentation.

---

## Document Model

| Term | Definition |
|------|-----------|
| **Shot** | The top-level authored document. Contains Scene, Camera2D, Canvas, Look, TraceDefaults, and a name. |
| **Scene** | Content container: shapes, lights, groups, and a named material library. |
| **Camera2D** | Authored camera framing. Optional `bounds`, `center`, or `width`. |
| **Canvas** | Output pixel dimensions (`width`, `height`). |
| **Look** | Authored display intent (exposure, tonemap, etc.). Saved in JSON. |
| **PostProcess** | Runtime GPU uniform state. Identical fields to Look; converted via `to_post_process()`. |
| **TraceDefaults** | Authored ray-tracing parameters (`rays`, `batch`, `depth`, `intensity`, `seed_mode`). |
| **TraceConfig** | Runtime trace parameters (`batch_size`, `depth`, `intensity`, `seed_mode`, `frame`). |

## Shapes

| Term | Definition |
|------|-----------|
| **Circle** | Center + radius. Fields: `center`, `radius`. |
| **Segment** | Line segment between two points. Fields: `a`, `b`. |
| **Arc** | Circular arc. Fields: `center`, `radius`, `angle_start`, `sweep`. |
| **Bezier** | Quadratic Bezier curve. Fields: `p0` (start), `p1` (control), `p2` (end). |
| **Polygon** | Closed polyline from `vertices`. Supports `corner_radius`, `corner_radii`, `join_modes`, and `smooth_angle`. |
| **Ellipse** | Axis-aligned then rotated ellipse. Fields: `center`, `semi_a`, `semi_b`, `rotation`. |
| **Path** | Chain of quadratic Bezier segments. Fields: `points` (2N+1 for N segments), `closed`. |
| **Shape** | Union type of all shape variants. |

## Polygon Geometry

| Term | Definition |
|------|-----------|
| **vertex / vertices** | Polygon corner positions. Always `vertices`, never "points" or "corners". |
| **edge** | Implicit segment connecting `vertices[i]` to `vertices[(i+1) % n]`. |
| **join** | Authored connection at a polygon vertex between the incoming and outgoing edges. |
| **PolygonJoinMode** | Per-vertex shading join enum: `auto`, `sharp`, or `smooth`. |
| **corner_radius** | Uniform bevel-fillet radius applied to convex corners. 0 = sharp. |
| **corner_radii** | Optional per-vertex bevel-fillet override. Must match `vertices.size()` if non-empty. |
| **join_modes** | Optional per-vertex shading join override. Entries are `auto`, `sharp`, or `smooth`. |
| **bevel fillet** | Arc-rounded corner operation (what `corner_radius` produces). Distinct from a future **bevel chamfer** (flat-cut). |
| **smooth_angle** | Radians threshold for `auto` polygon join smoothing. Shading only; does not change geometry. |
| **winding** | Polygon orientation. `polygon_is_clockwise()` tests signed area. |
| **convex** | A vertex where the interior angle < 180 deg. Only convex vertices receive bevel fillets. |

## Lights

| Term | Definition |
|------|-----------|
| **PointLight** | Omnidirectional point source. Fields: `position`, `intensity`, `wavelength_min`, `wavelength_max`. |
| **SegmentLight** | Linear source between two points. Fields: `a`, `b`, `intensity`, wavelength range. |
| **ProjectorLight** | Directional beam. Fields: `position`, `direction`, `source_radius`, `spread`, `profile`, `source`, `softness`, `intensity`, wavelength range. |
| **Light** | Union type of all light variants. |
| **intensity** | Total emitted power of a light source. |
| **emission** | Material field; shapes with `emission > 0` become light sources. |

## Materials

| Term | Definition |
|------|-----------|
| **Material** | Principled BSDF with 12 fields. |
| **ior** | Index of refraction (1.0 = vacuum). |
| **roughness** | 0 = specular mirror, 1 = Lambertian diffuse. |
| **metallic** | 0 = dielectric (Fresnel), 1 = conductor (flat reflectance = albedo). |
| **transmission** | Fraction of non-reflected light that refracts. 0 = opaque, 1 = glass. |
| **absorption** | Beer-Lambert coefficient inside medium (per unit distance). |
| **cauchy_b** | Cauchy dispersion: `ior_eff = ior + cauchy_b / lambda_nm^2`. |
| **albedo** | Metallic: reflectance F0. Dielectric: diffuse scatter probability. |
| **spectral_c0/c1/c2** | Sigmoid spectral color coefficients (Jakob & Hanika model). |
| **fill** | Interior fill intensity. 0 = no fill, >0 = rasterized solid interior. |
| **material_id** | String reference to a named entry in `Scene.materials`. |

### Material Constructors

`glass()`, `mirror()`, `opaque_mirror()`, `diffuse()`, `absorber()`, `emissive()`

Python wrappers in `anim/types.py` add a `color: ColorSpec` keyword for spectral color.

## Transform & Groups

| Term | Definition |
|------|-----------|
| **Transform2D** | Local-to-world transform: `translate`, `rotate` (radians), `scale` (Vec2). Applied: scale -> rotate -> translate. |
| **Group** | Container with `id`, `transform`, `shapes`, `lights`. One level only (no nesting). |

## Camera & Viewport

| Term | Definition |
|------|-----------|
| **Camera2D** | Authored camera framing (saved in Shot JSON). |
| **EditorCamera** | GUI viewport camera (`center` + `zoom`). Not serialized. |
| **CameraView** | Editor helper for world <-> screen coordinate conversion. |
| **Bounds** | Axis-aligned bounding box: `min`, `max` (both Vec2). |

## Rendering

| Term | Definition |
|------|-----------|
| **RenderSession** | Headless GPU render context. Methods: `render_shot()`, `render_frame()`, `postprocess()`. |
| **RenderResult** | Output: `pixels` (RGB8), `width`, `height`, `total_rays`, `max_hdr`, `metrics`, `time_ms`. |
| **rays** | Total ray count for a render. |
| **batch** / **batch_size** | Rays per GPU compute dispatch. |
| **depth** | Maximum ray bounce depth. |
| **frame** | Runtime frame index (for seed decorrelation and animation). |
| **SeedMode** | `deterministic` (same seed every frame) or `decorrelated` (varied per frame). |

## Post-Processing (Look / PostProcess)

| Term | Definition |
|------|-----------|
| **exposure** | Exposure in stops. |
| **tonemap** | Tone mapping operator: `none`, `reinhard`, `reinhardx`, `aces`, `log`. |
| **white_point** | White point for reinhardx/log tonemaps. |
| **normalize** | Normalization mode: `max`, `rays`, `fixed`, `off`. |
| **ambient** | Constant fill light added after exposure, before tonemap. |
| **background** | Linear RGB applied to unlit pixels. |
| **opacity** | Global opacity (fade-to-black). |
| **saturation** | Color saturation (1 = normal). |
| **vignette** / **vignette_radius** | Radial edge darkening. |
| **temperature** | Warm/cool color shift. |
| **highlights** / **shadows** | Pre-tonemap luminance adjustment. |
| **hue_shift** | Hue rotation in degrees. |
| **grain** / **grain_seed** | Film grain effect. |
| **chromatic_aberration** | Per-channel UV offset. |

## Statistics & Metrics

| Term | Definition |
|------|-----------|
| **FrameMetrics** | C++ luminance summary: `mean`, `median`, `shadow_floor`, `highlight_ceiling`, `near_black_fraction`, `clipped_channel_fraction`, `histogram`. |
| **FrameReport** | Python dataclass: enriched per-frame metadata from the renderer. |
| **FrameStats** | Python dataclass: luminance analysis from raw RGB8 pixels. |

## Animation (Python)

| Term | Definition |
|------|-----------|
| **Timeline** | Duration + fps. Derives `total_frames`, `dt`. |
| **FrameContext** | Immutable context per frame: `frame`, `time`, `progress`, `fps`, `dt`, `total_frames`, `duration`. |
| **Frame** | Return type for animate callbacks: `scene`, optional `camera`, `look`, `trace` overrides. |
| **AnimateFn** | `Callable[[FrameContext], Scene | Frame]` |
| **Track** | Keyframe interpolation with per-segment easing. |
| **Key** | Keyframe: `t` (time), `value`, `ease`. |
| **Wrap** | Track extrapolation: `clamp`, `loop`, `pingpong`. |
| **Quality** | Presets: `draft`, `preview`, `production`, `final`. |

## JSON Format

| Term | Definition |
|------|-----------|
| **version** | Integer. Current: **11**. Loaders reject any other value. |
| **Authored format** | Full explicit field sets for all blocks. No sparse keys in committed scenes. |
| **Named materials** | Top-level `materials` map. Shapes reference via `material_id`. |

## Coordinate Systems

| Term | Definition |
|------|-----------|
| **world space** | Unbounded 2D coordinates where scene geometry lives. |
| **screen space** | Window pixel coordinates (GUI only). |
| **pixel space** | Output image coordinates [0, width) x [0, height). |

## GPU / Shaders

| Term | Definition |
|------|-----------|
| **trace.comp** | Main ray-tracing compute shader. |
| **postprocess.frag** | Tone-mapping and post-effects fragment shader. |
| **fill.vert / fill.frag** | Shape interior rasterization. |
| **line.vert / line.frag** | Instanced line segment rendering. |
| **SSBO** | Shader Storage Buffer Object (per-shape-type GPU buffers). |
| **uMaxDepth** | Shader uniform for max bounce depth (maps from `TraceConfig.depth`). |
| **uToneMapOp** | Shader uniform for tonemap operator index. |
