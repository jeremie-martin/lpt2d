# Looking at scenes with diffuse materials

*(Some insights also applies to scenes with non-diffuse materials, this analyzis is more a serie of notes than a structure formal analyzis where the insights always only apply to the kind of scenes where they were found)*

## Main insights

Gamma does not appear to affect the radius of the light point’s apparent “circle of overexposed light,” but it is a strong lever for correcting overall exposure (both over- and under-exposure). In contrast, exposure and white point significantly impact the radius of this apparent circle and seem to play a similar role more broadly. The active sampler allows gamma to vary from 0.8 to 2.2.

An albedo in the range of 0.7–1.0 generally looks **much** better for diffuse surfaces than an albedo near 0.0.

There is also a case for allowing modest contrast adjustments; the active sampler uses 1.00–1.10.

## Preliminary note on filled colored diffuse objects

A fill range between 0.12 and 0.22 seems to work well. While exposure does not appear to affect color filling (which might be a bug, but could also be considered a feature), the filled color is influenced by contrast, gamma, white point, saturation, and temperature (along with a few less relevant factors).

While there is a strong argument for scenes with black objects (i.e., fill = 0), scenes with neutral gray objects (no color, fill between 0.12 and 0.22) can also look very good.

Until everything is fully under control and matches the intended result, it may be best to limit objects to a single diffuse color (i.e., no multiple colors per object).

---

# Looking at scenes with glassy materials (spheres)

When using a dispersion of 20000, the IOR should be between 1.4 and 1.55.

Higher dispersion increases the size/length of the caustics, while lower IOR decreases them. In terms of caustic size/length, it appears that:

* (IOR = 1.3, dispersion = 0) is roughly equivalent to (IOR = 1.5, dispersion = 50000)
* (IOR = 1.4, dispersion = 0) is roughly equivalent to (IOR = 1.5, dispersion = 25000)

Dispersion should likely not exceed 30000. As a rough approximation, 25000 dispersion may correspond to about 0.1 increase in IOR.

Fill color on glass objects looks better between 0.05 and 0.13.

Metallic and roughness should always be 0 (with transmission at 1.0).

---

# Apparent size of the light’s overexposed “circle”

The apparent size of the light’s overexposed “circle” varies significantly between moving and ambient lights, and this cannot be explained by intensity alone.

While increasing intensity generally increases the apparent circle size, this relationship is not stable across different spectral settings (wavelength ranges). Changes in the light spectrum can cause large variations (up to ~3×) in perceived size, even at identical intensities.

As a result, intensity alone is not sufficient to predict or control the apparent circle size. A more robust approach (e.g., image-based analysis) is needed, while using intensity, exposure, and post-processing parameters (gamma, contrast, white point) to achieve the desired visual result. We have implemented this image-based analysis but maybe we could work on making sure it's as robust and reliable as it gets.

In any case: the intensity range for both ambient and moving lights should be significantly expanded, and their ranges should largely overlap.

---

# Secondary parameters to consider once the primary ones are understood

A slight vignette can sometimes be beneficial. The maximum radius seems to be around 1.5, but extending it to 1.8 could be useful, with a vignette strength between 0.0 and 0.2 (e.g., 50% chance of a random value in that range, 50% chance of no vignette).

Occasional subtle chromatic aberration may improve scenes with colored objects (e.g., 50% chance of a value between 0.0 and 0.006, otherwise none). Chromatic aberration should not be used in scenes with glass materials, as it becomes too confusing.

A positive temperature (0.0–0.55) can look very good and could also be applied probabilistically (e.g., 50% of the time). Temperature seems to work well across most scene types. However, we should keep temperature at 0.0 for scenes with yellow or orange lights.

---

# Look filtering

While not the main focus, animations with a washed-out look (i.e., not enough contrast) should be rejected. This may become more common if contrast, gamma, and white point adjustments are introduced.

At the same time, there is a strong case for supporting wider look ranges:
exposure -8.0 to -2.0, gamma 0.8 to 2.2, contrast 1.00 to 1.10, and
white point 0.25 to 1.5.

Finally, the measurement of the apparent circle size of the lights should be made as robust as possible.
