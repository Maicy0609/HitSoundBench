// offsets_diag —— 逐 tile 时间轴诊断（用参考实现自己的 load_adofai）。
//
// 用来回答「两条时间轴为什么长度不同」这类问题：直接看参考实现算出的累计时间
// 有没有倒退、有没有零增量的整段（那会让累计时间戳停住/来回摆），并给出首个
// 异常位置附近的原始字段（angle / 前一个 angle / cw / midspin / 增量）。
#include "hitsound_core.hpp"

#include <cmath>
#include <cstddef>
#include <cstdio>

int main(int argc, char** argv) {
    if (argc < 2) {
        std::fprintf(stderr, "usage: offsets_diag <level.adofai>\n");
        return 2;
    }
    const std::vector<Tile> t = load_adofai(argv[1]);

    size_t n_back = 0, n_zero = 0, first_back = 0;
    double max_offset = 0.0, sum_dt = 0.0;
    for (size_t i = 1; i < t.size(); ++i) {
        const double d = t[i].offset - t[i - 1].offset;
        if (d < -1e-12) {
            if (n_back == 0) first_back = i;
            ++n_back;
        } else if (std::fabs(d) <= 1e-12) {
            ++n_zero;
        }
        if (t[i].offset > max_offset) max_offset = t[i].offset;
        sum_dt += d;
    }

    std::printf("tiles                = %zu\n", t.size() ? t.size() - 1 : 0);
    std::printf("末 tile offset       = %.4f s\n", t.empty() ? 0.0 : t.back().offset);
    std::printf("历史最大 offset      = %.4f s   （与末值之差 = %.4f s）\n",
                max_offset, max_offset - (t.empty() ? 0.0 : t.back().offset));
    std::printf("增量之和             = %.4f s\n", sum_dt);
    std::printf("offset 倒退的 tile   = %zu（首个 @ tile %zu）\n", n_back, first_back);
    std::printf("零增量（时长 0）tile = %zu\n", n_zero);

    auto dump = [&](size_t lo, size_t hi) {
        for (size_t i = lo; i <= hi && i < t.size(); ++i) {
            std::printf("  tile %8zu: angle=%9.3f prev=%9.3f cw=%d midspin=%d offset=%12.4f dt=%+12.7f\n",
                        i, t[i].angle, i ? t[i - 1].angle : 0.0, t[i].cw, (int)t[i].midspin,
                        t[i].offset, i ? t[i].offset - t[i - 1].offset : 0.0);
        }
    };
    if (first_back) {
        std::printf("\n首个倒退处附近:\n");
        dump(first_back > 6 ? first_back - 6 : 0, first_back + 6);
    }
    std::printf("\n末尾 12 个 tile:\n");
    dump(t.size() > 12 ? t.size() - 12 : 0, t.size() - 1);
    return 0;
}
