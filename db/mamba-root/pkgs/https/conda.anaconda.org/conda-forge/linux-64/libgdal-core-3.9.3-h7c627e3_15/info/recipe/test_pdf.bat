cd %~dp0\test_data

gdalinfo test_iso32000.pdf
if errorlevel 1 exit 1
