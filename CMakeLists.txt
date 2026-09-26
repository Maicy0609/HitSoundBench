cmake_minimum_required(VERSION 3.20)
project(HitSoundBench LANGUAGES C CXX)

# 剥离产物目录，由 extract/extract.sh 生成（不进版本控制，避免代码副本漂移）
set(EXTRACT_DIR "${CMAKE_CURRENT_SOURCE_DIR}/build/extracted"
    CACHE PATH "上游剥离产物目录")

if(NOT EXISTS "${EXTRACT_DIR}/adocao/core/timeline/Timeline.cpp")
    message(FATAL_ERROR "缺少剥离产物：请先运行 extract/extract.sh（或 scripts/run_bench.sh）")
endif()

# ── 依赖：完全沿用上游的选择（rapidjson 头文件库 + miniz 单文件 zip 库）──
include(FetchContent)
if(POLICY CMP0169)
    cmake_policy(SET CMP0169 OLD)   # rapidjson 无可用 CMake 构建，只能 Populate
endif()

FetchContent_Declare(rapidjson
    GIT_REPOSITORY https://github.com/Tencent/rapidjson.git
    GIT_TAG v1.1.0
    GIT_SHALLOW TRUE)
FetchContent_GetProperties(rapidjson)
if(NOT rapidjson_POPULATED)
    FetchContent_Populate(rapidjson)
endif()

FetchContent_Declare(miniz
    GIT_REPOSITORY https://github.com/richgel999/miniz.git
    GIT_TAG 3.0.2
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(miniz)
target_include_directories(miniz PUBLIC ${miniz_SOURCE_DIR})

# ── 编译选项：两侧同为 -O2，不开 -march=native / LTO（保持可比性）──
if(MSVC)
    add_compile_options(/O2 /EHsc /W3 /utf-8)
else()
    add_compile_options(-O2)
endif()

# ── ADOCAO 侧：复用其 core（解析/时间轴）+ HitsoundManager（合成），C++20 ──
add_executable(adocao_gen
    src/adocao_gen.cpp
    ${EXTRACT_DIR}/adocao/core/level/LevelData.cpp
    ${EXTRACT_DIR}/adocao/core/level/JsonCleaner.cpp
    ${EXTRACT_DIR}/adocao/core/timeline/Timeline.cpp
    ${EXTRACT_DIR}/adocao/core/util/Logger.cpp
    ${EXTRACT_DIR}/adocao/core/util/DataFile.cpp
    ${EXTRACT_DIR}/adocao/audio/HitsoundManager.cpp)
target_include_directories(adocao_gen PRIVATE
    ${EXTRACT_DIR}/adocao      # "core/..." 与 "audio/HitsoundManager.hpp"
    ${EXTRACT_DIR}/shims      # AudioEngine.hpp 的最小替身
    ${rapidjson_SOURCE_DIR}/include)
target_link_libraries(adocao_gen PRIVATE miniz)
target_compile_features(adocao_gen PRIVATE cxx_std_20)

# ── ADOFAI_HitSound 侧：剥离后的 HitSound.cpp，C++17（与上游一致）──
add_executable(ref_gen
    src/ref_main.cpp
    ${EXTRACT_DIR}/ref/hitsound_core.cpp)
target_include_directories(ref_gen PRIVATE
    ${EXTRACT_DIR}/ref
    ${rapidjson_SOURCE_DIR}/include)
target_compile_features(ref_gen PRIVATE cxx_std_17)

if(MSVC)
    target_compile_definitions(adocao_gen PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
    target_compile_definitions(ref_gen    PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
endif()
if(WIN32)
    # probe.hpp 的峰值内存（GetProcessMemoryInfo）
    target_link_libraries(adocao_gen PRIVATE psapi)
    target_link_libraries(ref_gen    PRIVATE psapi)
endif()
