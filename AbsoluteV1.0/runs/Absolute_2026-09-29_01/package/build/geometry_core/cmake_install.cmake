# Install script for directory: /mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/src/geometry_core

# Set the install prefix
if(NOT DEFINED CMAKE_INSTALL_PREFIX)
  set(CMAKE_INSTALL_PREFIX "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/install/geometry_core")
endif()
string(REGEX REPLACE "/$" "" CMAKE_INSTALL_PREFIX "${CMAKE_INSTALL_PREFIX}")

# Set the install configuration name.
if(NOT DEFINED CMAKE_INSTALL_CONFIG_NAME)
  if(BUILD_TYPE)
    string(REGEX REPLACE "^[^A-Za-z0-9_]+" ""
           CMAKE_INSTALL_CONFIG_NAME "${BUILD_TYPE}")
  else()
    set(CMAKE_INSTALL_CONFIG_NAME "Release")
  endif()
  message(STATUS "Install configuration: \"${CMAKE_INSTALL_CONFIG_NAME}\"")
endif()

# Set the component getting installed.
if(NOT CMAKE_INSTALL_COMPONENT)
  if(COMPONENT)
    message(STATUS "Install component: \"${COMPONENT}\"")
    set(CMAKE_INSTALL_COMPONENT "${COMPONENT}")
  else()
    set(CMAKE_INSTALL_COMPONENT)
  endif()
endif()

# Install shared libraries without execute permission?
if(NOT DEFINED CMAKE_INSTALL_SO_NO_EXE)
  set(CMAKE_INSTALL_SO_NO_EXE "1")
endif()

# Is this installation the result of a crosscompile?
if(NOT DEFINED CMAKE_CROSSCOMPILING)
  set(CMAKE_CROSSCOMPILING "FALSE")
endif()

# Set default install directory permissions.
if(NOT DEFINED CMAKE_OBJDUMP)
  set(CMAKE_OBJDUMP "/usr/bin/objdump")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/include" TYPE DIRECTORY FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/src/geometry_core/include/")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/lib" TYPE STATIC_LIBRARY FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/libgeometry_core.a")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/opt/ros/jazzy/lib/python3.12/site-packages/ament_package/template/environment_hook/library_path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/library_path.dsv")
endif()

if(NOT CMAKE_INSTALL_LOCAL_ONLY)
  # Include the install script for the subdirectory.
  include("/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/gtest/cmake_install.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/package_run_dependencies" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_index/share/ament_index/resource_index/package_run_dependencies/geometry_core")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/parent_prefix_path" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_index/share/ament_index/resource_index/parent_prefix_path/geometry_core")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/opt/ros/jazzy/share/ament_cmake_core/cmake/environment_hooks/environment/ament_prefix_path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/ament_prefix_path.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/opt/ros/jazzy/share/ament_cmake_core/cmake/environment_hooks/environment/path.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/environment" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/path.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/local_setup.bash")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/local_setup.sh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/local_setup.zsh")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/local_setup.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_environment_hooks/package.dsv")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/ament_index/resource_index/packages" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_index/share/ament_index/resource_index/packages/geometry_core")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  if(EXISTS "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake/geometry_core_targetsExport.cmake")
    file(DIFFERENT _cmake_export_file_changed FILES
         "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake/geometry_core_targetsExport.cmake"
         "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/CMakeFiles/Export/a156f89804614fa0fae7c54d3e643e1d/geometry_core_targetsExport.cmake")
    if(_cmake_export_file_changed)
      file(GLOB _cmake_old_config_files "$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake/geometry_core_targetsExport-*.cmake")
      if(_cmake_old_config_files)
        string(REPLACE ";" ", " _cmake_old_config_files_text "${_cmake_old_config_files}")
        message(STATUS "Old export file \"$ENV{DESTDIR}${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake/geometry_core_targetsExport.cmake\" will be replaced.  Removing files [${_cmake_old_config_files_text}].")
        unset(_cmake_old_config_files_text)
        file(REMOVE ${_cmake_old_config_files})
      endif()
      unset(_cmake_old_config_files)
    endif()
    unset(_cmake_export_file_changed)
  endif()
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/CMakeFiles/Export/a156f89804614fa0fae7c54d3e643e1d/geometry_core_targetsExport.cmake")
  if(CMAKE_INSTALL_CONFIG_NAME MATCHES "^([Rr][Ee][Ll][Ee][Aa][Ss][Ee])$")
    file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/CMakeFiles/Export/a156f89804614fa0fae7c54d3e643e1d/geometry_core_targetsExport-release.cmake")
  endif()
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_export_targets/ament_cmake_export_targets-extras.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_export_dependencies/ament_cmake_export_dependencies-extras.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_export_include_directories/ament_cmake_export_include_directories-extras.cmake")
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core/cmake" TYPE FILE FILES
    "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_core/geometry_coreConfig.cmake"
    "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/ament_cmake_core/geometry_coreConfig-version.cmake"
    )
endif()

if(CMAKE_INSTALL_COMPONENT STREQUAL "Unspecified" OR NOT CMAKE_INSTALL_COMPONENT)
  file(INSTALL DESTINATION "${CMAKE_INSTALL_PREFIX}/share/geometry_core" TYPE FILE FILES "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/src/geometry_core/package.xml")
endif()

if(CMAKE_INSTALL_COMPONENT)
  set(CMAKE_INSTALL_MANIFEST "install_manifest_${CMAKE_INSTALL_COMPONENT}.txt")
else()
  set(CMAKE_INSTALL_MANIFEST "install_manifest.txt")
endif()

string(REPLACE ";" "\n" CMAKE_INSTALL_MANIFEST_CONTENT
       "${CMAKE_INSTALL_MANIFEST_FILES}")
file(WRITE "/mnt/c/Users/alanpeng/Desktop/Self-envolve_agent/AbsoluteV1.0/runs/Absolute_2026-09-29_01/package/build/geometry_core/${CMAKE_INSTALL_MANIFEST}"
     "${CMAKE_INSTALL_MANIFEST_CONTENT}")
