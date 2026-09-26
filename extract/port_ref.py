#!/usr/bin/env python3
"""把 ADOFAI_HitSound/HitSound.cpp 剥离成可跨平台构建的 hitsound_core.{hpp,cpp}。

原则：**音频算法一行不改**，只做四件事，每件事都用断言卡住——上游一改结构就
立刻报错退出，而不是悄悄产出一份行为不同的副本（那会让基准失去意义）。

  1. 去 Windows 化：去掉 windows.h / shlwapi.h / 控制台代码，以及依赖
     AudioLoudnorm.dll 的 EBU R128 后处理段（带外 DLL，与合成算法无关）
  2. hit.wav 路径改为命令行传入（上游是从 exe 目录里找）
  3. 附加：导出奈奎斯特过滤后保留的 hit 时间（秒）到 timeline 文件（对齐比较用）
  4. 去掉上游的交互式 main()

用法: port_ref.py <上游 HitSound.cpp> <输出目录>
"""
import pathlib
import re
import sys
from datetime import datetime, timezone

BANNER = "// ══════════════════════════════════════════════════════════════"

# ── 切片标记（上游结构锚点）────────────────────────────────────────────────
M_TILE = "// ── Tile ──"
M_LOAD = "// ── 谱面加载"
M_GEN = "// ── 合成"
M_LOUD = "// ── 响度平衡后处理"

PROLOGUE = """// ── 平台无关的头文件（由 port_ref.py 生成，替代上游的 windows.h/shlwapi.h）──
#include <algorithm>
#include <cmath>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <cstring>
#include <fstream>
#include <iostream>
#include <string>
#include <unordered_map>
#include <vector>

#include "rapidjson/document.h"

#include "hitsound_core.hpp"

// 上游在文件顶部定义、被 load_adofai / generate 引用的全局开关：剥离时顶部整段被本文件替换，
// 所以这里补一份（基准里保持上游默认值）。
static bool g_apply_offset = true;
static bool g_nyquist = true;

"""

DECLS = """// ── 基准入口（附加声明，非上游内容）──────────────────────────────────────────
std::vector<Tile> load_adofai(const std::string& path);
void generate(const std::vector<Tile>& tiles, const std::string& out_path,
              const std::string& hitwav_path, const std::string& dump_path);
"""


def cut(src: str, marker: str, name: str, occurrence: int = 0) -> int:
    """定位标记，强制唯一（occurrence=0 表示必须只出现一次）。"""
    n = src.count(marker)
    if n == 0:
        sys.exit(f"[port_ref] 上游找不到锚点 {name}: {marker!r} —— 结构变了，请检查上游")
    if occurrence == 0 and n != 1:
        sys.exit(f"[port_ref] 上游锚点 {name} 出现 {n} 次（期望 1 次）—— 结构变了，请检查上游")
    return src.index(marker)


def sub_once(text: str, old: str, new: str, what: str) -> str:
    if text.count(old) != 1:
        sys.exit(f"[port_ref] 替换失败（{what}）: {old[:60]!r} 出现 {text.count(old)} 次")
    return text.replace(old, new)


def main() -> None:
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    src_path, out_dir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
    src = src_path.read_text(encoding="utf-8-sig")

    # ── 切片 ──
    i_tile = cut(src, M_TILE, "Tile 结构")
    i_load = cut(src, M_LOAD, "谱面加载段")
    i_gen = cut(src, M_GEN, "合成段")
    i_loud_hdr = cut(src, M_LOUD, "响度后处理段")
    i_loud = src.rindex(BANNER, 0, i_loud_hdr)          # 连同段首分隔线一起丢掉

    struct_text = src[i_tile:i_load]
    core = src[i_load:i_gen] + src[i_gen:i_loud]

    # ── (1)+(2)+(4)：去 Windows 化 / 路径外部化 ──
    core = sub_once(core, "static std::vector<Tile> load_adofai(",
                    "std::vector<Tile> load_adofai(", "load_adofai 去 static")
    core = sub_once(
        core,
        "static void generate(const std::vector<Tile>& tiles, const std::string& out_path)",
        "void generate(const std::vector<Tile>& tiles, const std::string& out_path,\n"
        "              const std::string& hitwav_path, const std::string& dump_path)",
        "generate 去 static + 换签名")

    # 上游从这里取 exe 同目录的 hit.wav；基准里由命令行传入（两侧用同一个样本）
    i_hdr = core.index("    // hit.wav 路径")
    i_fp = core.index("    FILE* fp = fopen(wav_path.c_str(), \"rb\");")
    core = core[:i_hdr] + "    std::string wav_path = hitwav_path;\n\n" + core[i_fp:]

    # ── (3)：导出过滤后保留的 hit 时间（附加代码，算法不动）──
    anchor = ("        pins.push_back((int64_t)(offset * (double)sr));\n"
              "        vols.push_back((float)(tiles[i].volume / 100.0));\n"
              "    }\n")
    core = sub_once(core, anchor, anchor + "\n" + """    // ── 基准附加：导出保留的 hit 时间（二进制 float64，单位秒）──
    // 巨型关卡下文本格式会让 Python 侧爆内存，故用二进制；写一次 fwrite。
    if (!dump_path.empty()) {
        std::vector<double> sec(pins.size());
        for (size_t i = 0; i < pins.size(); ++i)
            sec[i] = (double)pins[i] / (double)sr;
        FILE* dp = fopen(dump_path.c_str(), "wb");
        if (dp) {
            if (!sec.empty()) fwrite(sec.data(), sizeof(double), sec.size(), dp);
            fclose(dp);
        }
    }
""", "hit 时间导出钩子")

    if "GetModuleFileNameA" in core or "shlwapi" in core or "LoadLibraryA" in core:
        sys.exit("[port_ref] 仍有 Windows-only 残留 —— 请检查上游改动")

    # ── 落盘 ──
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    banner = (f"// ⚠ 由 extract/port_ref.py 于 {stamp} 从 {src_path.name} 自动剥离，请勿手改。\n"
              "// 生成规则与改写清单见 extract/port_ref.py（算法原文，只做去 Windows 化 + 换入口）。\n")
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "hitsound_core.hpp").write_text(
        banner + "#pragma once\n#include <algorithm>   // Tile::update 用到 std::max\n"
                 "#include <cmath>       // Tile::update 用到 fmod\n"
                 "#include <string>\n#include <vector>\n\n"
        + struct_text + "\n" + DECLS, encoding="utf-8")
    (out_dir / "hitsound_core.cpp").write_text(
        banner + PROLOGUE + core, encoding="utf-8")

    kept = len(re.findall(r"^\s*$", core, re.M))
    print(f"[port_ref] {src_path} → {out_dir}/hitsound_core.{{hpp,cpp}}"
          f"（{len(core.splitlines())} 行算法正文，改写 4 处，断言全过）")


if __name__ == "__main__":
    main()
