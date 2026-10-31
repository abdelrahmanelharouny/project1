#!/bin/bash

# exit when any command fails
set -e
# print all commands
set -x

pushd $( dirname "${BASH_SOURCE[0]}" )/test_data/

gdalinfo test_iso32000.pdf

popd
