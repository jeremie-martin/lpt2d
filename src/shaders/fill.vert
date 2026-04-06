#version 430 core

layout(location = 0) in vec2 aPosition;
layout(location = 1) in vec3 aColor;

uniform vec2 uBoundsMin;
uniform vec2 uViewScale;
uniform vec2 uViewOffset;
uniform vec2 uResolution;

out vec3 vColor;

void main() {
    vec2 pixel = (aPosition - uBoundsMin) * uViewScale + uViewOffset;
    vec2 ndc = (pixel / uResolution) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    vColor = aColor;
}
