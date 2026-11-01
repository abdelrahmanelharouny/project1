#! /bin/bash
set -ex

mkdir build
cd build

if [[ "${build_platform}" == "${target_platform}" ]]; then
    export CMAKE_ARGS="${CMAKE_ARGS} -DBUILD_TESTING=ON"
fi

if [[ "${target_platform}" == "linux-"* ]]; then
    export LDFLAGS="$LDFLAGS -Wl,--exclude-libs,ALL"
elif [[ "${target_platform}" == "osx-"* ]]; then
    export LDFLAGS="$LDFLAGS -Wl,-unexported_symbol,_zip*"
    export CXXFLAGS="$CXXFLAGS -D_LIBCPP_ENABLE_CXX17_REMOVED_UNARY_BINARY_FUNCTION"
fi


export CMAKE_POLICY_VERSION_MINIMUM=3.5

cmake ${CMAKE_ARGS} \
    -DCMAKE_INSTALL_PREFIX=$PREFIX \
    ..

cmake --build .

if [[ "${build_platform}" == "${target_platform}" ]]; then
    DYLD_FALLBACK_LIBRARY_PATH=${PREFIX}/lib ctest --progress --output-on-failure
fi

make install -j $CPU_COUNT

rm -rf $PREFIX/include/minizip
rm -rf $PREFIX/lib/libminizip*
