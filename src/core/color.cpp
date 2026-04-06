#include "color.h"

static const NamedColorEntry kNamedColors[] = {
    {"red",    {650.0f, 40.0f}},
    {"orange", {600.0f, 35.0f}},
    {"amber",  {590.0f, 25.0f}},
    {"yellow", {575.0f, 30.0f}},
    {"green",  {530.0f, 40.0f}},
    {"cyan",   {490.0f, 30.0f}},
    {"blue",   {465.0f, 30.0f}},
    {"violet", {420.0f, 25.0f}},
    {nullptr,  {0.0f, 0.0f}},
};

std::optional<SpectralParams> named_color(std::string_view name) {
    for (const auto* entry = kNamedColors; entry->name; ++entry) {
        if (name == entry->name)
            return entry->params;
    }
    return std::nullopt;
}

const NamedColorEntry* named_colors() { return kNamedColors; }

int named_color_count() {
    int n = 0;
    for (const auto* e = kNamedColors; e->name; ++e) ++n;
    return n;
}
