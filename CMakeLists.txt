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

# miniz 的 CMakeLists 里写着 cmake_minimum_required(VERSION 3.0)，CMake 4.x 默认直接拒绝
# （Windows runner 上的 CMake 是 4.4）。用它自己报错信息里给的逃生阀降到 3.5；
# CMake 3.31 上没这个变量，设置了也无害。
if(NOT DEFINED CMAKE_POLICY_VERSION_MINIMUM)
    set(CMAKE_POLICY_VERSION_MINIMUM 3.5)
endif()

FetchContent_Declare(miniz
    GIT_REPOSITORY https://github.com/richgel999/miniz.git
    GIT_TAG 3.0.2
    GIT_SHALLOW TRUE)
FetchContent_MakeAvailable(miniz)
target_include_directories(miniz PUBLIC ${miniz_SOURCE_DIR})

# ── 编译优化档 ──────────────────────────────────────────────────────────────
# project（默认）：**各自项目自己的 Release 档**，也就是「各自按作者的方式编译」：
#     ADOCAO      : -O3 -march=native -fomit-frame-pointer（它的 CMakeLists.txt:55）
#     参考实现    : 它自己文档里的 cl /O2 /arch:AVX2（GCC 侧对应 -O2 + AVX2）
#                   MSVC 侧用 /O2 /Ob3 /arch:AVX2 近似 ADOCAO 的 -march=native
# uniform：两侧都退到 -O2（不带 AVX2/native），只用来观察"排除优化差异后"的差距。
#
# 起因：issue #2 —— 早先版本给两侧统一 -O2，把 ADOCAO 的 Release 档降级了。
set(HITSOUNDBENCH_OPT "project" CACHE STRING "编译优化档：project | uniform")

if(MSVC)
    set(BENCH_WARN /EHsc /W3 /utf-8)
    if(HITSOUNDBENCH_OPT STREQUAL "project")
        set(ADOCAO_OPT /O2 /Ob3 /arch:AVX2)     # 近似 ADOCAO 的 -O3 -march=native
        set(REF_OPT    /O2 /arch:AVX2)          # 参考实现文档里的编译命令行
    else()
        set(ADOCAO_OPT /O2)
        set(REF_OPT    /O2)
    endif()
else()
    set(BENCH_WARN -Wall)
    if(HITSOUNDBENCH_OPT STREQUAL "project")
        set(ADOCAO_OPT -O3 -march=native -fomit-frame-pointer)
        if(CMAKE_SYSTEM_PROCESSOR MATCHES "^(x86_64|AMD64|amd64)$")
            set(REF_OPT -O2 -mavx2)             # 对应参考实现文档里的 /arch:AVX2
        else()
            set(REF_OPT -O2)
        endif()
    else()
        set(ADOCAO_OPT -O2)
        set(REF_OPT    -O2)
    endif()
endif()
message(STATUS "优化档 = ${HITSOUNDBENCH_OPT}：adocao_gen[${ADOCAO_OPT}] ref_gen[${REF_OPT}]")

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
target_compile_options(adocao_gen PRIVATE ${BENCH_WARN} ${ADOCAO_OPT})

# ── ADOFAI_HitSound 侧：剥离后的 HitSound.cpp，C++17（与上游一致）──
add_executable(ref_gen
    src/ref_main.cpp
    ${EXTRACT_DIR}/ref/hitsound_core.cpp)
target_include_directories(ref_gen PRIVATE
    ${EXTRACT_DIR}/ref
    ${rapidjson_SOURCE_DIR}/include)
target_compile_features(ref_gen PRIVATE cxx_std_17)
target_compile_options(ref_gen PRIVATE ${BENCH_WARN} ${REF_OPT})

# ── 时间轴诊断：逐 tile 看参考实现算出的累计时间（回答「时长为什么不同」）──
add_executable(offsets_diag
    tools/offsets_diag.cpp
    ${EXTRACT_DIR}/ref/hitsound_core.cpp)
target_include_directories(offsets_diag PRIVATE
    ${EXTRACT_DIR}/ref
    ${rapidjson_SOURCE_DIR}/include)
target_compile_features(offsets_diag PRIVATE cxx_std_17)
target_compile_options(offsets_diag PRIVATE ${BENCH_WARN} ${REF_OPT})

if(MSVC)
    target_compile_definitions(adocao_gen PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
    target_compile_definitions(ref_gen    PRIVATE NOMINMAX _CRT_SECURE_NO_WARNINGS)
endif()
if(WIN32)
    # probe.hpp 的峰值内存（GetProcessMemoryInfo）
    target_link_libraries(adocao_gen PRIVATE psapi)
    target_link_libraries(ref_gen    PRIVATE psapi)
endif()
