#pragma once
// probe.hpp —— 基准指标采集
//
// 唯一职责：分阶段计时 + 峰值内存 + 以 key=value 形式落盘。
// 不含任何音频/时间轴逻辑，两侧入口（adocao_gen / ref_gen）共用同一份采集口径。
#ifdef _WIN32
#  ifndef NOMINMAX
#    define NOMINMAX
#  endif
#  include <windows.h>
#  include <psapi.h>
#endif

#include <chrono>
#include <cstdio>
#include <string>
#include <utility>
#include <vector>

struct Probe {
    using Clock = std::chrono::steady_clock;

    std::vector<std::pair<std::string, double>> values;   // 输出顺序 = 插入顺序
    Clock::time_point t0 = Clock::now();

    static double msSince(Clock::time_point t) {
        return std::chrono::duration<double, std::milli>(Clock::now() - t).count();
    }

    // 计时一个阶段（名字 → <name>_ms）
    template <class F>
    double time(const std::string& name, F&& fn) {
        const auto t = Clock::now();
        fn();
        const double ms = msSince(t);
        values.emplace_back(name + "_ms", ms);
        return ms;
    }

    void kv(const std::string& key, double value) { values.emplace_back(key, value); }

    static long peakRssKB() {
#ifdef _WIN32
        PROCESS_MEMORY_COUNTERS pmc{};
        if (GetProcessMemoryInfo(GetCurrentProcess(), &pmc, sizeof(pmc)))
            return static_cast<long>(pmc.PeakWorkingSetSize / 1024);
        return -1;
#else
        FILE* f = std::fopen("/proc/self/status", "r");
        if (!f) return -1;
        char line[256];
        long kb = -1;
        while (std::fgets(line, sizeof(line), f))
            if (std::sscanf(line, "VmHWM: %ld kB", &kb) == 1) break;
        std::fclose(f);
        return kb;
#endif
    }

    // 收尾：总量 + 峰值内存（必须在所有阶段结束后调用一次）
    void finish() {
        values.emplace_back("total_ms", msSince(t0));
        values.emplace_back("peak_rss_kb", static_cast<double>(peakRssKB()));
    }

    void write(const std::string& path) const {
        FILE* f = std::fopen(path.c_str(), "w");
        if (!f) { std::fprintf(stderr, "[probe] cannot write %s\n", path.c_str()); return; }
        for (const auto& [k, v] : values) std::fprintf(f, "%s=%.3f\n", k.c_str(), v);
        std::fclose(f);
    }

    void dumpToStdout() const {
        for (const auto& [k, v] : values) std::printf("[probe] %s=%.3f\n", k.c_str(), v);
        std::fflush(stdout);
    }
};
