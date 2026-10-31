#!/bin/bash
# Get an updated config.sub and config.guess
cp $BUILD_PREFIX/share/gnuconfig/config.* .

cmake ${CMAKE_ARGS} -D CMAKE_PREFIX_PATH=$PREFIX \
      -D CMAKE_INSTALL_PREFIX=$PREFIX \
      -D WITH_PROJ4=ON \
      -D WITH_ZLIB=ON \
      -D BUILD_SHARED_LIBS=ON \
      -D WITH_JPEG=ON \
      -D WITH_TIFF=ON \
      $SRC_DIR

make -j${CPU_COUNT}
make install

# Make sure GEOTIFF_CSV and set and still present in the package.
ACTIVATE_DIR=$PREFIX/etc/conda/activate.d
DEACTIVATE_DIR=$PREFIX/etc/conda/deactivate.d
mkdir -p $ACTIVATE_DIR
mkdir -p $DEACTIVATE_DIR

cp $RECIPE_DIR/scripts/activate.sh $ACTIVATE_DIR/geotiff-activate.sh
cp $RECIPE_DIR/scripts/deactivate.sh $DEACTIVATE_DIR/geotiff-deactivate.sh

