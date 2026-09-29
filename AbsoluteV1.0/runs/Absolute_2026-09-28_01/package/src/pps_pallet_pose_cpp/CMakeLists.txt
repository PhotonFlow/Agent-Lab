cmake_minimum_required(VERSION 3.16)
project(pps_pallet_pose_cpp CXX)

if(NOT CMAKE_CXX_STANDARD)
  set(CMAKE_CXX_STANDARD 17)
  set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()
add_compile_options(-Wall -Wextra)

find_package(ament_cmake REQUIRED)
find_package(rclcpp REQUIRED)
find_package(sensor_msgs REQUIRED)
find_package(vision_msgs REQUIRED)
find_package(geometry_msgs REQUIRED)
find_package(diagnostic_msgs REQUIRED)
find_package(builtin_interfaces REQUIRED)
find_package(message_filters REQUIRED)
find_package(ament_index_cpp REQUIRED)
find_package(geometry_core REQUIRED)
find_package(pps_perception_msgs REQUIRED)
find_package(OpenCV REQUIRED COMPONENTS core)
find_package(Eigen3 REQUIRED)

add_executable(pallet_pose_cpp_node
  src/depth_utils.cpp
  src/detection_utils.cpp
  src/pallet_pose_node.cpp
  src/pallet_pose_node_main.cpp
)
target_include_directories(pallet_pose_cpp_node PRIVATE include ${OpenCV_INCLUDE_DIRS})
ament_target_dependencies(pallet_pose_cpp_node
  rclcpp sensor_msgs vision_msgs geometry_msgs diagnostic_msgs builtin_interfaces
  message_filters ament_index_cpp pps_perception_msgs Eigen3
)
target_link_libraries(pallet_pose_cpp_node geometry_core::geometry_core ${OpenCV_LIBS} Eigen3::Eigen)

install(TARGETS pallet_pose_cpp_node DESTINATION lib/${PROJECT_NAME})
install(DIRECTORY launch DESTINATION share/${PROJECT_NAME} OPTIONAL)
install(DIRECTORY config DESTINATION share/${PROJECT_NAME} OPTIONAL)

if(BUILD_TESTING)
  find_package(ament_cmake_gtest REQUIRED)
  ament_add_gtest(test_depth_utils test/test_depth_utils.cpp src/depth_utils.cpp)
  target_include_directories(test_depth_utils PRIVATE include ${OpenCV_INCLUDE_DIRS})
  ament_target_dependencies(test_depth_utils sensor_msgs)
  target_link_libraries(test_depth_utils ${OpenCV_LIBS})
  ament_add_gtest(test_detection_utils test/test_detection_utils.cpp src/detection_utils.cpp)
  target_include_directories(test_detection_utils PRIVATE include)
  ament_target_dependencies(test_detection_utils vision_msgs Eigen3)
  target_link_libraries(test_detection_utils Eigen3::Eigen)
endif()

ament_package()
