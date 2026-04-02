#define STB_IMAGE_WRITE_IMPLEMENTATION
#include "stb_image_write.h"

#include "export.h"

bool export_png(const std::string& path, const uint8_t* rgb, int width, int height) {
    return stbi_write_png(path.c_str(), width, height, 3, rgb, width * 3) != 0;
}
