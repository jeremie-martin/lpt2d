#pragma once

#include <cstdint>
#include <string>

bool export_png(const std::string& path, const uint8_t* rgb, int width, int height);
