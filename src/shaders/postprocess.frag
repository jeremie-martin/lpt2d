#version 430 core
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D uFloatTexture;
uniform sampler2D uFillTexture;
uniform float uMaxVal;
uniform float uExposureMult;
uniform float uContrast;
uniform float uInvGamma;
uniform int uToneMapOp;
uniform float uWhitePoint;
uniform float uAmbient;
uniform vec3 uBackground;
uniform float uOpacity;
uniform float uSaturation;
uniform float uVignette;
uniform float uVignetteRadius;
uniform vec2 uVignetteCenter;
uniform vec2 uVignetteInvSize;
uniform float uVignetteXScale;
uniform float uTemperature;
uniform float uHighlights;
uniform float uShadows;
uniform mat3 uHueRot;
uniform float uGrain;
uniform int uGrainSeed;
uniform float uChromaticAberration;

float toneMapReinhard(float v) { return v / (1.0 + v); }

float toneMapReinhardExt(float v, float wp) {
    float w2 = wp * wp;
    return (v * (1.0 + v / w2)) / (1.0 + v);
}

float toneMapACES(float v) {
    float a = 2.51, b = 0.03, c = 2.43, d = 0.59, e = 0.14;
    return clamp((v * (a * v + b)) / (v * (c * v + d) + e), 0.0, 1.0);
}

float toneMapLog(float v, float wp) {
    return log(1.0 + v) / log(1.0 + wp);
}

float toneMap(float v, int op, float wp) {
    if (op == 1) return toneMapReinhard(v);
    if (op == 2) return toneMapReinhardExt(v, wp);
    if (op == 3) return toneMapACES(v);
    if (op == 4) return toneMapLog(v, wp);
    return clamp(v, 0.0, 1.0);
}

void main() {
    vec2 flippedCoord = vec2(TexCoord.x, 1.0 - TexCoord.y);

    vec4 hdr;
    if (uChromaticAberration > 0.0) {
        vec2 dir = flippedCoord - vec2(0.5);
        hdr.r = texture(uFloatTexture, flippedCoord + dir * uChromaticAberration).r;
        hdr.g = texture(uFloatTexture, flippedCoord).g;
        hdr.b = texture(uFloatTexture, flippedCoord - dir * uChromaticAberration).b;
        hdr.a = 1.0;
    } else {
        hdr = texture(uFloatTexture, flippedCoord);
    }

    vec3 color = hdr.rgb / uMaxVal * uExposureMult;

    // Add fill color (shape interiors) — sampled from a separate RGB16F texture
    vec3 fillColor = texture(uFillTexture, flippedCoord).rgb;
    color += fillColor;

    // Background replaces pixels with negligible light; threshold is in
    // post-exposure space so it works consistently across normalization modes.
    vec3 mask = step(vec3(1e-6), color);
    color = mix(uBackground, color + uAmbient, mask);

    // Highlights / shadows: luminance-weighted pre-tonemap lift
    if (uHighlights != 0.0 || uShadows != 0.0) {
        float lum = dot(color, vec3(0.2126, 0.7152, 0.0722));
        float sw = 1.0 - smoothstep(0.0, 0.5, lum);
        float hw = smoothstep(0.5, 1.0, lum);
        color += color * uShadows * sw + color * uHighlights * hw;
        color = max(color, vec3(0.0));
    }

    // Tone mapping
    for (int c = 0; c < 3; c++)
        color[c] = toneMap(color[c], uToneMapOp, uWhitePoint);

    // Contrast
    color = clamp((color - 0.5) * uContrast + 0.5, 0.0, 1.0);

    // Saturation in post-tonemap linear space (BT.709 luminance weights).
    // Integer approximation (218/732/74 >>10) used in renderer.cpp and stats.py.
    if (uSaturation != 1.0) {
        float lum = dot(color, vec3(0.2126, 0.7152, 0.0722));
        color = clamp(mix(vec3(lum), color, uSaturation), 0.0, 1.0);
    }

    if (uTemperature != 0.0)
        color *= vec3(1.0 + uTemperature * 0.3, 1.0, 1.0 - uTemperature * 0.3);

    // Hue rotation (precomputed on CPU; identity when hue_shift == 0)
    color = clamp(uHueRot * color, 0.0, 1.0);

    // Gamma
    color = pow(color, vec3(uInvGamma));

    // Film grain: hash-based noise in display space
    if (uGrain > 0.0) {
        vec2 seed = flippedCoord + vec2(float(uGrainSeed) * 0.7123, float(uGrainSeed) * 0.3217);
        float noise = fract(sin(dot(seed, vec2(12.9898, 78.233))) * 43758.5453) - 0.5;
        color = clamp(color + noise * uGrain, 0.0, 1.0);
    }

    // Vignette: radial edge darkening
    if (uVignette > 0.0) {
        vec2 uv = (flippedCoord - uVignetteCenter) * uVignetteInvSize;
        uv.x *= uVignetteXScale;
        float dist = length(uv) * 2.0;
        float vig = 1.0 - uVignette * smoothstep(uVignetteRadius, uVignetteRadius + 0.5, dist);
        color *= vig;
    }

    color *= uOpacity;
    FragColor = vec4(color, 1.0);
}
