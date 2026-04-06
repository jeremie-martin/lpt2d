#pragma once

#include <optional>
#include <string_view>

struct SpectralParams {
    float wavelength; // peak nm
    float bandwidth;  // Gaussian sigma nm
};

struct NamedColorEntry {
    const char* name;
    SpectralParams params;
};

// Resolve a named color to spectral parameters. Returns nullopt for unknown names.
std::optional<SpectralParams> named_color(std::string_view name);

// List all known named colors (null-terminated array).
const NamedColorEntry* named_colors();
int named_color_count();
