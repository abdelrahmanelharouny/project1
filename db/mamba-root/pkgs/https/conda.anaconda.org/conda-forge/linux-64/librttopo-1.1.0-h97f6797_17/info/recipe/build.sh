#!/bin/bash
# Get an updated config.sub and config.guess
cp $BUILD_PREFIX/share/gnuconfig/config.* .

./configure \
    --prefix=${PREFIX} \
    --libdir=${PREFIX}/lib \
    --includedir=${PREFIX}/include \
    --with-geosconfig=$PREFIX/bin/geos-config

make
if [[ "${CONDA_BUILD_CROSS_COMPILATION:-}" != "1" || "${CROSSCOMPILING_EMULATOR}" != "" ]]; then
make check
fi
make install

# remove the static library
rm -f ${PREFIX}/lib/librttopo.a
