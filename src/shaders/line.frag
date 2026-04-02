#version 430 core
in vec4 vColor;
in float vLineDist;
out vec4 FragColor;

void main() {
    float alpha = 1.0 - smoothstep(0.5, 1.0, abs(vLineDist));
    FragColor = vColor * alpha;
}
