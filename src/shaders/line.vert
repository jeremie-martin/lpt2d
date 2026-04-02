#version 430 core

struct LineSeg {
    vec2 p0;
    vec2 p1;
    vec4 color;
};

layout(std430, binding = 3) readonly buffer OutputBuf { LineSeg segs[]; };

uniform vec2 uResolution;
uniform float uThickness;

out vec4 vColor;
out float vLineDist;

void main() {
    uint seg_id = gl_InstanceID;
    LineSeg s = segs[seg_id];

    vec2 dir = s.p1 - s.p0;
    float len = length(dir);
    if (len < 0.001) { gl_Position = vec4(0); return; }

    vec2 n = vec2(-dir.y, dir.x) / len * uThickness;

    // 6 vertices per quad: 0,1,2 = tri1; 3,4,5 = tri2
    vec2 pos;
    float dist;
    int vid = gl_VertexID;
    if      (vid == 0) { pos = s.p0 - n; dist = -1.0; }
    else if (vid == 1) { pos = s.p0 + n; dist =  1.0; }
    else if (vid == 2) { pos = s.p1 - n; dist = -1.0; }
    else if (vid == 3) { pos = s.p0 + n; dist =  1.0; }
    else if (vid == 4) { pos = s.p1 + n; dist =  1.0; }
    else               { pos = s.p1 - n; dist = -1.0; }

    vec2 ndc = (pos / uResolution) * 2.0 - 1.0;
    ndc.y = -ndc.y;
    gl_Position = vec4(ndc, 0.0, 1.0);
    vColor = s.color;
    vLineDist = dist;
}
