set -exo pipefail

SOURCE_DIR="${PWD}"
TZDATA_DIR="${PWD}/tzdata"

# tzcode lacks tzdata inputs; bring in only missing files from the secondary
# tzdata source so upstream make targets can run without file collisions.
if [[ -d "${TZDATA_DIR}" ]]; then
  shopt -s nullglob dotglob
  for src in "${TZDATA_DIR}"/*; do
    dst="${SOURCE_DIR}/$(basename "${src}")"
    if [[ ! -e "${dst}" ]]; then
      cp -a "${src}" "${dst}"
    fi
  done
  shopt -u nullglob dotglob
fi

if [[ $(uname) == Darwin ]]; then
  CFLAGS="$CFLAGS -DHAVE_GETRANDOM=0"
fi

if [[ "$CONDA_BUILD_CROSS_COMPILATION" == 1 ]]; then
  FOR_BUILD_DIR="$(mktemp -d)"
  cp -a "${SOURCE_DIR}/." "${FOR_BUILD_DIR}/"
  pushd "${FOR_BUILD_DIR}"

  # Keep data outputs out of the prefix while using upstream install logic.
  BUILD_TZDIR="${PWD}/zoneinfo"
  BUILD_TZDEFAULT="${PWD}/localtime"
  BUILD_MANDIR="${PWD}/man"

  make -e \
    CC=${CC_FOR_BUILD} \
    TOPDIR=${BUILD_PREFIX} \
    USRDIR="" \
    ZICDIR="${BUILD_PREFIX}/bin" \
    TZDIR="${BUILD_TZDIR}" \
    MANDIR="${BUILD_MANDIR}" \
    TZDEFAULT="${BUILD_TZDEFAULT}" \
    install

  popd
  rm -rf "${FOR_BUILD_DIR}"
  MAKE_EXTRA_ARGS="zic=${BUILD_PREFIX}/bin/zic"
fi

cd "${SOURCE_DIR}"

# Use upstream install, but keep data outputs outside PREFIX so this remains code-only.
PKG_TZDIR="${PWD}/zoneinfo"
PKG_TZDEFAULT="${PWD}/localtime"
PKG_MANDIR="${PWD}/man"

make -e \
  CC=${CC} \
  TOPDIR=${PREFIX} ${MAKE_EXTRA_ARGS:-} \
  USRDIR="" \
  ZICDIR="${PREFIX}/bin" \
  TZDIR="${PKG_TZDIR}" \
  MANDIR="${PKG_MANDIR}" \
  TZDEFAULT="${PKG_TZDEFAULT}" \
  install
