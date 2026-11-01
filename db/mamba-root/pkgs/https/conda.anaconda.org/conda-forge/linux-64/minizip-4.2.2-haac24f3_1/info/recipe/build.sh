#!/bin/bash
set -ex

mkdir build
cd build

cmake ${CMAKE_ARGS} \
  -DCMAKE_INSTALL_PREFIX="${PREFIX}" \
  -DBUILD_SHARED_LIBS=ON \
  -DMZ_ZLIB_FLAVOR=zlib \
  -DCMAKE_BUILD_TYPE=Release \
  -DMZ_BUILD_TESTS=ON \
  -DMZ_BUILD_UNIT_TESTS=ON \
  -DMZ_LIBCOMP=OFF \
  -DMZ_OPENSSL=ON \
  -DMZ_ZLIB=ON \
  -DMZ_FORCE_FETCH_LIBS=OFF \
  ..

cmake --build .

if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR}" != "" ]]; then
ctest --output-on-failure
fi

cmake --install .

cd ..
