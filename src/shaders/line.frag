#version 430 core
flat in vec3 vColor;
noperspective in float vLineDist;
out vec4 FragColor;

void main() {
    float alpha = 1.0 - smoothstep(0.5, 1.0, abs(vLineDist));
    FragColor = vec4(vColor * alpha, 1.0);
}
