#pragma once

// Minimal in-tree test runner for lpt2d-core.
// Self-registering tests, source-location diagnostics, no external dependencies.

#include <cmath>
#include <cstdio>
#include <functional>
#include <source_location>
#include <string>
#include <vector>

namespace test {

struct TestCase {
    std::string name;
    std::function<void()> fn;
};

inline std::vector<TestCase>& registry() {
    static std::vector<TestCase> cases;
    return cases;
}

inline int& fail_count() {
    static int n = 0;
    return n;
}

struct Register {
    Register(const char* name, std::function<void()> fn) {
        registry().push_back({name, std::move(fn)});
    }
};

inline void fail(const char* expr, std::source_location loc = std::source_location::current()) {
    std::fprintf(stderr, "  FAIL: %s\n    at %s:%u\n", expr, loc.file_name(), loc.line());
    ++fail_count();
}

inline void check(bool cond, const char* expr,
                  std::source_location loc = std::source_location::current()) {
    if (!cond) fail(expr, loc);
}

inline void check_near(float a, float b, float tol, const char* expr,
                       std::source_location loc = std::source_location::current()) {
    if (std::abs(a - b) > tol) {
        std::fprintf(stderr, "  FAIL: %s  (%.8f vs %.8f, tol=%.8f)\n    at %s:%u\n",
                     expr, a, b, tol, loc.file_name(), loc.line());
        ++fail_count();
    }
}

inline int run_all() {
    int passed = 0, failed = 0;
    for (auto& tc : registry()) {
        int before = fail_count();
        tc.fn();
        if (fail_count() == before) {
            ++passed;
            std::printf("  PASS: %s\n", tc.name.c_str());
        } else {
            ++failed;
            std::printf("  FAIL: %s\n", tc.name.c_str());
        }
    }
    std::printf("\n%d passed, %d failed\n", passed, failed);
    return failed > 0 ? 1 : 0;
}

} // namespace test

#define TEST(name)                                            \
    static void test_##name();                                \
    static test::Register reg_##name(#name, test_##name);     \
    static void test_##name()

#define ASSERT_TRUE(expr)       test::check((expr), #expr)
#define ASSERT_FALSE(expr)      test::check(!(expr), "!(" #expr ")")
#define ASSERT_NEAR(a, b, tol)  test::check_near((a), (b), (tol), #a " ~= " #b)
#define ASSERT_EQ(a, b)         test::check((a) == (b), #a " == " #b)
