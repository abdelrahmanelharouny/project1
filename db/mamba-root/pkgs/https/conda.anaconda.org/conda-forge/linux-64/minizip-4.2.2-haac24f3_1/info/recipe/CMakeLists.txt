cmake_minimum_required(VERSION 3.15)
project(minizip_consumer LANGUAGES C)

find_package(minizip CONFIG REQUIRED)

add_executable(minizip_consumer test_minizip.c)
target_link_libraries(minizip_consumer PRIVATE MINIZIP::minizip)
