#version 430 core
in vec2 TexCoord;
out vec4 FragColor;

uniform sampler2D uFloatTexture;
uniform float uMaxVal;
uniform float uExposureMult;
uniform float uContrast;
uniform float uInvGamma;
uniform int uToneMapOp;
uniform float uWhitePoint;
uniform float uAmbient;
uniform vec3 uBackground;
uniform float uOpacity;

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
    vec4 hdr = texture(uFloatTexture, flippedCoord);

    vec3 color;
    for (int c = 0; c < 3; c++) {
        float v = hdr[c];
        v = v / uMaxVal;
        v = v * uExposureMult;
        // Background replaces pixels with negligible light; threshold is in
        // post-exposure space so it works consistently across normalization modes.
        if (v < 1e-6) v = uBackground[c];
        else v = v + uAmbient;
        v = toneMap(v, uToneMapOp, uWhitePoint);
        v = (v - 0.5) * uContrast + 0.5;
        v = clamp(v, 0.0, 1.0);
        v = pow(v, uInvGamma);
        color[c] = v;
    }

    color *= uOpacity;
    FragColor = vec4(color, 1.0);
}
