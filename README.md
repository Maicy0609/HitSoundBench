# HitSoundBench

把两个冰与火之舞（ADOFAI）打拍音生成器的**同一件事**放到同一台机器上跑，用同一份谱面、
同一个打击音样本对比：**耗时 / 内存 / 时间轴 / 音频本身**。

- 被测 A：**ADOCAO** 的 `core/timeline` + `audio/HitsoundManager`（16-bit 逐样本硬削波）
- 被测 B：**ADOFAI_HitSound** 的 `HitSound.cpp`（奈奎斯特过滤 + 静态等功率预缩放）
- 测试谱面：`Tempest.adofai` —— 158,403 tiles / 158,402 hits / 最大同时发声 879
- 打击音：**两侧都用 ADOFAI_HitSound 仓库里那唯一的 `hit.wav`**（48 kHz / 16-bit / 11,101 帧）

代码不做副本：`extract/` 每次从上游仓库现取现剥离（ADOCAO 逐字复制、`HitSound.cpp` 由脚本
去 Windows 化），上游一更新重跑即可，不存在两份源码漂移的问题。

## 怎么跑

### ① GitHub Actions（手动触发，不会自己跑）

Actions 页面 → 左侧 `bench` → **Run workflow**：

| 输入 | 说明 |
|---|---|
| `runs` | 每个工具重复跑几次（默认 3，取最快一次的产物，其余只留指标） |
| `adocao_ref` | 钉 ADOCAO 的提交/分支（留空 = 默认分支） |
| `hitsound_ref` | 钉 ADOFAI_HitSound 的提交/分支（留空 = 默认分支） |

或用命令行：

```bash
gh workflow run bench -f runs=3
gh run watch $(gh run list --workflow=bench --limit 1 --json databaseId -q '.[0].databaseId')
```

workflow 只在 `workflow_dispatch` 上触发，**没有** push / PR / 定时触发；仓库是 public，
标准 runner 的 Actions 分钟数不占用额度。

矩阵：`ubuntu-latest`（GCC，与 ADOCAO 的 Linux 构建一致）+ `windows-latest`（MSVC，ADOFAI_HitSound 的原生工具链）。

### ② 本地

```bash
RUNS=3 bash scripts/run_bench.sh                    # 自动从 GitHub 取上游
ADOCAO_SRC=/path/to/ADOCAO HITSOUND_SRC=/path/to/ADOFAI_HitSound \
    RUNS=3 bash scripts/run_bench.sh                # 用本地工作副本（开发用）
```

需要：CMake ≥ 3.20、C++20 编译器、Python 3 + `numpy`、`matplotlib`（画图用）。
首次构建会 FetchContent 拉 RapidJSON 与 miniz（上游自己也是这么拉的）。

## 产物（每次运行的 Artifacts）

| 文件 | 内容 |
|---|---|
| `adocao.wav` / `ref.wav` | 两侧的**完整原始输出**，未做任何剪辑 |
| `ab_sparse.wav` / `ab_dense.wav` | A/B 试听：**左耳 ADOCAO、右耳 ADOFAI_HitSound**，同一区间、各自归一到 −20 dBFS |
| `ab_*_raw.wav` | 同上，但保留原始电平（想听「原样输出」的响度差就用这个） |
| `report.md` | 报告：性能表 / 时间轴一致性 / 音频指标 / 响度动态 |
| `report.json` | 同样的数字，机器可读 |
| `compare.png` | 全曲响度包络 + 稀疏段 / 最密段波形 |
| `metrics_*.txt` / `timeline_*.txt` / `log_*.txt` | 每次运行的原始指标、hit 时间轴、完整 stdout |
| `PROVENANCE.txt` | 本次跑的是上游哪个仓库的哪个 commit（含本地副本是否有未提交改动） |

## 测量口径

- 两侧同为 `-O2`、同一台机器、同一次运行；**不开** `-march=native` / LTO / PGO（保持可比）。
- 阶段耗时由 `src/probe.hpp` 记录（`steady_clock`），峰值内存取进程峰值 RSS
  （Linux `/proc/self/status` 的 `VmHWM`，Windows `GetProcessMemoryInfo`）。
- 两侧阶段划分不同，报告里逐行标注了口径（ADOCO 拆成 解析 / 角度传播+前缀和 / 混音 / 写盘；
  ADOFAI_HitSound 是 `load_adofai` + `generate` 两段）。不要跨行错位对比。
- 时间轴一致性用**最近邻匹配**而不是逐下标比较：ref 会丢掉奈奎斯特过滤掉的重复 hit，
  逐下标会因为集合不同而整体错位。

## 已知的、不是 bug 的差异

| 差异 | 原因 |
|---|---|
| 首击偏移：ADOCO 0 s，ref 0.6 s | ADOCO 的缓冲以「下标 0 = 第一次击打」对齐（前导静音交给播放器 pre-roll）；ref 直接输出含前导静音的整轨 |
| 命中数：ADOCO 比 ref 多 4,988 个 | ref 的奈奎斯特过滤丢弃间隔 < 1/(sr/2) ≈ 41.7 µs 的重复 hit（Tempest 上正好 4,988 个，两边自报一致） |
| 整体增益差约 25 dB | ADOCO 逐样本硬削波顶到满量程；ref 按 1/√879 预缩放并把峰值留在 −14 dBFS（它另有可选的 EBU R128 后处理来补响度） |
| 声道：2 vs 1 | ADOCO 输出立体声（L=R 复制），ref 输出单声道 |

## 本地冒烟结果（仅参考，正式结果看 Actions）

6 核容器、Tempest、`hit.wav`、各自跑 1 次：

| 阶段 | ADOCAO | ADOFAI_HitSound |
|---|---:|---:|
| 解析谱面 | 754.5 ms | 433.8 ms（含 `Tile::update` 链式累积） |
| 角度/BPM 传播 + 前缀和 | 18.6 ms | 含在上一行 |
| 合成 + 混音 | 4,260.9 ms | 1,844.0 ms（含滤波 + 密度统计 + 写盘） |
| 写 WAV | 44.6 ms | 含在上一行 |
| **总计** | **5,160.5 ms** | **2,277.9 ms**（ADOCO 是它的 2.27×） |
| 峰值内存 | 186.1 MB | 156.0 MB |
| 整体 RMS / 峰值 | −7.06 dBFS / 32,767（削波 0.334%） | −29.83 dBFS / 6,189（0 削波） |
| 包络动态范围 (P95−P5) | 5.96 dB | 12.25 dB |

时间轴：两侧逐击一致（最近邻最大偏差 0.021 ms = 一个采样；4,988 个多出的 hit 全部落在保留
hit 的 41.7 µs 邻域内）。

## 目录

```
extract/          剥离脚本：extract.sh（取源）+ port_ref.py / patch_adocao.py（改写）+ shims/
src/              两侧的薄入口 adocao_gen / ref_main + 共用的指标采集 probe.hpp
tools/            analyze.py（报告与图表）+ audio_metrics.py（WAV/指标计算）
scripts/          run_bench.sh（本地与 CI 共用的唯一编排入口）
.github/workflows/bench.yml   手动触发的矩阵 workflow
```

## 结果怎么解读

- **性能**：ADOCO 的混音循环每个样本要做两次 clamp（还写两声道），且没有先算密度；
  ref 每样本只做一次 double 累加，并用差分数组先求出最大同时发声数。差距主要来自这里。
- **音频**：ADR 方案（ADOCO）的密集段是硬削波饱和，ref 是常数增益 + 峰值安全余量。
  报告第 4 节给出各自的削波比例、包络动态范围，`ab_*.wav` 可以直接听出来。
- 想让两者响度真正可比，请用 `ab_*.wav`（增益对齐版），不要用两个 `*.wav` 直接对放。
