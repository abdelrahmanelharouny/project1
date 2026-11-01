
:: Had to set TIFF_NAMES, PROJ4_NAMES and JPEG_NAMES to force use of shared libs
:: Note that zlib and jpeg only get linked in if tiff is linked statically, otherwise
:: they don't seem to be used (presumeably they are used via libtiff in a dll build).
cmake -G "NMake Makefiles" ^
      -D CMAKE_BUILD_TYPE=Release ^
      -D CMAKE_PREFIX_PATH=%LIBRARY_PREFIX% ^
      -D CMAKE_INSTALL_PREFIX=%LIBRARY_PREFIX% ^
      -D WITH_ZLIB=ON ^
      -D BUILD_SHARED_LIBS=ON ^
      -D WITH_JPEG=ON ^
      -D WITH_TIFF=ON ^
      -D TIFF_NAMES=tiff ^
      -D PROJ_NAMES=proj_6_1 ^
      -D JPEG_NAMES=libjpeg ^
      %SRC_DIR%
if errorlevel 1 exit 1

nmake
if errorlevel 1 exit 1

nmake install
if errorlevel 1 exit 1

set ACTIVATE_DIR=%PREFIX%\etc\conda\activate.d
set DEACTIVATE_DIR=%PREFIX%\etc\conda\deactivate.d
mkdir %ACTIVATE_DIR%
mkdir %DEACTIVATE_DIR%

copy %RECIPE_DIR%\scripts\activate.bat %ACTIVATE_DIR%\geotiff-activate.bat
if errorlevel 1 exit 1

copy %RECIPE_DIR%\scripts\deactivate.bat %DEACTIVATE_DIR%\geotiff-deactivate.bat
if errorlevel 1 exit 1

:: Copy unix shell activation scripts, needed by Windows Bash users
copy %RECIPE_DIR%\scripts\activate.sh %ACTIVATE_DIR%\geotiff-activate.sh
if errorlevel 1 exit 1

copy %RECIPE_DIR%\scripts\deactivate.sh %DEACTIVATE_DIR%\geotiff-deactivate.sh
if errorlevel 1 exit 1
