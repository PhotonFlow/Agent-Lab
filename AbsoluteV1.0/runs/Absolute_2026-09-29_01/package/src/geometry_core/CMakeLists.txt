cmake_minimum_required(VERSION 3.16)
project(geometry_core CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-O3 -Wall -Wextra)

find_package(ament_cmake REQUIRED)
find_package(Eigen3 REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core imgproc)
find_package(yaml-cpp REQUIRED)
find_package(OpenMP REQUIRED)

add_library(geometry_core
  src/version.cpp
  src/transforms.cpp
  src/pose.cpp
  src/plane_fit.cpp
  src/plane_coords.cpp
  src/face_mask.cpp
  src/camera_config.cpp
  src/prototype.cpp
  src/chamfer.cpp
  src/pca_init.cpp
  src/chamfer_prior.cpp
  src/backproject.cpp
  src/pipeline_v3_2.cpp
)
target_include_directories(geometry_core PUBLIC
  $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/include>
  $<INSTALL_INTERFACE:include>
)
target_link_libraries(geometry_core PUBLIC
  Eigen3::Eigen
  ${OpenCV_LIBS}
  yaml-cpp
)
target_include_directories(geometry_core PUBLIC ${OpenCV_INCLUDE_DIRS})
target_link_libraries(geometry_core PUBLIC OpenMP::OpenMP_CXX)

install(DIRECTORY include/ DESTINATION include)
install(TARGETS geometry_core
  EXPORT geometry_core_targets
  LIBRARY DESTINATION lib
  ARCHIVE DESTINATION lib
  RUNTIME DESTINATION bin
)
ament_export_targets(geometry_core_targets HAS_LIBRARY_TARGET)
ament_export_dependencies(Eigen3 OpenCV yaml-cpp OpenMP)
ament_export_include_directories(include)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_version test/test_version.cpp)
  target_link_libraries(test_version geometry_core)
  ament_add_gtest(test_transforms test/test_transforms.cpp)
  target_link_libraries(test_transforms geometry_core)
  ament_add_gtest(test_pose test/test_pose.cpp)
  target_link_libraries(test_pose geometry_core)
  ament_add_gtest(test_plane_fit test/test_plane_fit.cpp)
  target_link_libraries(test_plane_fit geometry_core)
  ament_add_gtest(test_plane_coords test/test_plane_coords.cpp)
  target_link_libraries(test_plane_coords geometry_core)
  ament_add_gtest(test_face_mask test/test_face_mask.cpp)
  target_link_libraries(test_face_mask geometry_core)
  ament_add_gtest(test_camera_config test/test_camera_config.cpp)
  target_link_libraries(test_camera_config geometry_core)
  ament_add_gtest(test_prototype test/test_prototype.cpp)
  target_link_libraries(test_prototype geometry_core)
  ament_add_gtest(test_chamfer test/test_chamfer.cpp)
  target_link_libraries(test_chamfer geometry_core)
  ament_add_gtest(test_pca_init test/test_pca_init.cpp)
  target_link_libraries(test_pca_init geometry_core)
  ament_add_gtest(test_chamfer_prior test/test_chamfer_prior.cpp)
  target_link_libraries(test_chamfer_prior geometry_core)
  ament_add_gtest(test_backproject test/test_backproject.cpp)
  target_link_libraries(test_backproject geometry_core)
  ament_add_gtest(test_pipeline_v3_2 test/test_pipeline_v3_2.cpp)
  target_link_libraries(test_pipeline_v3_2 geometry_core)
endif()

ament_package()
