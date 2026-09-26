// ref_main —— ADOFAI_HitSound 侧的基准入口
//
// 职责：调用剥离出的 load_adofai / generate（算法原文，见 extract/port_ref.py），
// 把交互式 CLI 换成一次性的命令行调用，便于自动跑。
#include "hitsound_core.hpp"
#include "probe.hpp"

#include <cstdio>
#include <string>
#include <vector>

int main(int argc, char** argv) {
    if (argc < 6) {
        std::fprintf(stderr,
                     "usage: ref_gen <level.adofai> <hit.wav> <out.wav> <metrics.txt> <timeline.txt>\n");
        return 2;
    }
    const std::string levelPath = argv[1], hitWav = argv[2];
    const std::string outWav = argv[3], metricsPath = argv[4], timelinePath = argv[5];

    Probe probe;

    std::vector<Tile> tiles;
    probe.time("load", [&] { tiles = load_adofai(levelPath); });

    // generate 内部自带奈奎斯特过滤 → 密度统计 → 预缩放 → 混音 → 写 WAV，
    // 因此这里只能给一个总时长；明细由它自己打印到 stdout（进 CI 日志）。
    probe.time("generate", [&] { generate(tiles, outWav, hitWav, timelinePath); });

    probe.kv("tiles", static_cast<double>(tiles.size()));
    probe.finish();

    probe.write(metricsPath);
    probe.dumpToStdout();
    return 0;
}
