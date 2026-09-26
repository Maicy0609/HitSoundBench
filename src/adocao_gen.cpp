// adocao_gen —— ADOCAO 侧的基准入口
//
// 职责：调用 ADOCAO 剥离出的 core + audio 走完「读谱 → 时间轴 → 合成 → 导出 WAV」。
// 与上游 app/Application.cpp 的 `--export` 分支等价，不新增/不改动任何音频算法；
// 不含 GLFW / OpenGL / 窗口（上游的 --export 因为排在 glfwInit 之后而需要显示器）。
#include "probe.hpp"

#include "audio/HitsoundManager.hpp"
#include "core/level/LevelData.hpp"
#include "core/timeline/Timeline.hpp"
#include "core/util/Logger.hpp"

#include <algorithm>
#include <cstdio>
#include <string>
#include <vector>

namespace {

// 导出 hit 时间（秒）供报告做时间轴对齐比较；分组顺序打散，故需排序。
// 二进制 float64：巨型关卡（上千万 hit）下文本格式会让 Python 侧内存和耗时爆掉。
void writeTimeline(const std::vector<HitsoundTimestampGroup>& groups, const std::string& path) {
    std::vector<double> all;
    size_t total = 0;
    for (const auto& g : groups) total += g.timestamps.size();
    all.reserve(total);
    for (const auto& g : groups) all.insert(all.end(), g.timestamps.begin(), g.timestamps.end());
    std::sort(all.begin(), all.end());

    FILE* f = std::fopen(path.c_str(), "wb");
    if (!f) return;
    if (!all.empty()) std::fwrite(all.data(), sizeof(double), all.size(), f);
    std::fclose(f);

    std::printf("[probe] timeline_dump hits=%zu bytes=%zu\n", all.size(),
                all.size() * sizeof(double));
}

}  // namespace

int main(int argc, char** argv) {
    if (argc < 6) {
        std::fprintf(stderr,
                     "usage: adocao_gen <level.adofai> <assetsDir> <out.wav> <metrics.txt> <timeline.f64>\n");
        return 2;
    }
    const std::string levelPath = argv[1];
    // HitsoundManager::init() 期望「带分隔符结尾」的资源目录（上游 findAssetsDir
    // 就是返回 ".../hitsounds/"），这里补上，避免调用方记这种细节。
    std::string assetsDir = argv[2];
    if (!assetsDir.empty() && assetsDir.back() != '/' && assetsDir.back() != '\\') assetsDir += '/';
    const std::string outWav = argv[3], metricsPath = argv[4], timelinePath = argv[5];

    Probe probe;
    Logger::instance().init("adocao_gen.log", /*debugConsole=*/true);

    LevelData level;
    bool loaded = false;
    probe.time("load", [&] { loaded = level.loadFromFile(levelPath, nullptr, /*exportOnly=*/true); });
    if (!loaded) {
        std::fprintf(stderr, "load failed: %s\n", levelPath.c_str());
        return 1;
    }

    Timeline timeline;
    probe.time("timeline", [&] { timeline.build(level, /*exportOnly=*/true); });

    HitsoundManager hitsounds;
    hitsounds.init(assetsDir);

    const std::vector<HitsoundTimestampGroup> groups = timeline.getHitsoundTimestampGroups();
    int hits = 0;
    for (const auto& g : groups) hits += static_cast<int>(g.timestamps.size());

    bool synthesized = false;
    probe.time("synthesize",
               [&] { synthesized = hitsounds.preSynthesize(groups, timeline.totalDuration()); });
    if (!synthesized) {
        std::fprintf(stderr, "preSynthesize failed\n");
        return 1;
    }

    bool written = false;
    probe.time("write_wav", [&] { written = hitsounds.writeWav(outWav); });
    if (!written) {
        std::fprintf(stderr, "writeWav failed: %s\n", outWav.c_str());
        return 1;
    }
    writeTimeline(groups, timelinePath);

    probe.kv("tiles", static_cast<double>(level.angleData.size() + 1));
    probe.kv("hits", hits);
    probe.kv("groups", static_cast<double>(groups.size()));
    probe.kv("level_duration_s", timeline.totalDuration());
    probe.kv("out_frames", static_cast<double>(hitsounds.totalFrames()));
    probe.kv("out_sample_rate", hitsounds.sampleRate());
    probe.kv("out_channels", hitsounds.channels());
    probe.finish();

    probe.write(metricsPath);
    probe.dumpToStdout();
    return 0;
}
