@echo on

@rem apps/CMakeLists.txt still declares cmake_minimum_required(VERSION 2.8),
@rem which CMake >=4 rejects outright.
cmake -GNinja -S . -B build ^
  %CMAKE_ARGS% ^
  -DCMAKE_BUILD_TYPE=Release ^
  -DCMAKE_INSTALL_PREFIX="%LIBRARY_PREFIX%" ^
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5
if errorlevel 1 exit 1

cmake --build build
if errorlevel 1 exit 1

cmake --install build
if errorlevel 1 exit 1
