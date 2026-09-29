#include <cstring>

#include <gtest/gtest.h>

#include "geometry_core/version.hpp"

TEST(Version, IsNonEmpty) {
  ASSERT_NE(geometry_core::kVersion, nullptr);
  EXPECT_GT(std::strlen(geometry_core::kVersion), 0u);
}
