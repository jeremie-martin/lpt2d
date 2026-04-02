# Roadmap

Engine features needed before animation work can begin. Each step is independently shippable.

## Layer 1 — Expressive power

### Scene serialization (JSON save/load)
Unblocks iteration on scene design. The editor can create scenes but can't save them — every design is lost on close, and new scenes require recompilation. A JSON format that round-trips `Scene` makes the editor a real tool. Also a hard prerequisite for animation (scene parameters changing over time needs a serializable representation).

### Beam light (directional / collimated)
A light source defined by position + direction + angular width. The "laser pointer" — the most visually striking light type for optics. Replaces the current slit hacks in prism and double_slit scenes. Small addition, huge visual payoff.

### Colored / wavelength-filtered lights
Every light currently emits the full 380–780nm spectrum uniformly. Adding `wavelength_min` and `wavelength_max` per light (or center + bandwidth for Gaussian emission) enables: monochromatic beams that don't disperse, narrow-band sources for interference, warm/cool toned lamps. Minimal shader change, massive artistic control.

### Arc primitive
Circular arc defined by center, radius, angle_start, angle_end. Trivially extends existing circle intersection (clamp the hit angle). Enables: curved mirrors, parabolic reflectors, lenses with controlled aperture, crescents, half-pipes.

### Glossy reflection (roughness)
A roughness parameter on specular materials — perturb the reflection direction by a random angle scaled by roughness. Bridges the gap between perfect mirror and Lambertian diffuse. One float, a few shader lines. Enables: brushed metal, frosted glass, soft reflections.

### Quadratic Bezier curves
Defined by 3 control points. Ray-bezier intersection in 2D is a cubic solve (closed form). Opens up smooth organic shapes, waveguides, freeform optics. More complex intersection math than arcs, but much more expressive.

## Layer 2 — Workflow

### Transform groups
Group shapes together, apply translate/rotate/scale to the group. Without this, moving a composite object (e.g. a prism = 3 segments) means moving each piece individually. Prerequisite for animation — you animate group transforms, not individual vertices.

## Layer 3 — Visual polish

### Bloom post-processing
Gaussian blur added to bright areas, blended back. Separable 2-pass blur on the float FBO (~50 lines of shader). Makes light sources glow and caustics feel luminous. Enormous visual impact for minimal code.

### Background gradient
The void is currently black. A subtle radial or linear gradient background makes renders feel finished instead of floating in nothing.
