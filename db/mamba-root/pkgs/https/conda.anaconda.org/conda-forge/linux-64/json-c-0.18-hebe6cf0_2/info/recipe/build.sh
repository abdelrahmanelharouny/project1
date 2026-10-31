#!/bin/bash
set -euxo pipefail

# The test suite relies on assertions: https://github.com/json-c/json-c/issues/406
export CPPFLAGS="${CPPFLAGS/-DNDEBUG/}"

# apps/CMakeLists.txt still declares cmake_minimum_required(VERSION 2.8),
# which CMake >=4 rejects outright.
cmake -GNinja -S . -B build \
  ${CMAKE_ARGS} \
  -DCMAKE_BUILD_TYPE=Release \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DCMAKE_POLICY_VERSION_MINIMUM=3.5

cmake --build build

if [[ "${CONDA_BUILD_CROSS_COMPILATION:-0}" != "1" ]]; then
  ctest --test-dir build --output-on-failure
fi

cmake --install build
