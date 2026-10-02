# HitSoundBench

把两个冰与火之舞（ADOFAI）打拍音生成器的**同一件事**放到同一台机器上跑，用同一份谱面、
同一个打击音样本对比：**耗时 / 内存 / 时间轴 / 音频本身**。

- 被测 A：**ADOCAO** 的 `core/timeline` + `audio/HitsoundManager`（16-bit 逐样本硬削波）
- 被测 B：**ADOFAI_HitSound** 的 `HitSound.cpp`（奈奎斯特过滤 + 静态等功率预缩放）
- 测试谱面（`LEVELS` 可选，逗号分隔）：
  - `tempest` —— 上游 ADOFAI_HitSound 仓库的 `x64/Release/Tempest.adofai`（158,403 tiles）
  - `level` —— 本仓库 `levels/level.zip` 里的 `level.adofai`（**压缩包 15.7 MB，解压后 315 MB**，
    所以压缩包原样提交、**只在跑的时候解压**，解压产物不进版本库）
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

优化档由 `OPT` 决定（`project` = 默认）：

| 档位 | ADOCAO | 参考实现 | 用途 |
| --- | --- | --- | --- |
| **`project`（默认）** | 它自己的 Release 档：`-O3 -march=native -fomit-frame-pointer`（`CMakeLists.txt:55`）；MSVC 侧用 `/O2 /Ob3 /arch:AVX2` 近似 | 它自己文档里的编译命令行：`cl /O2 /arch:AVX2`（GCC 侧对应 `-O2 -mavx2`） | **各自按作者的方式编译** —— 对外引用的口径 |
| `uniform` | `-O2` | `-O2` | 排除优化差异后的对照 |

> 早先版本不管两边设置、统一用 `-O2`（而且它压过了 CMake Release 自带的 `-O3`），等于把 ADOCAO
> 的 Release 档降级 —— 这是 [issue #2](https://github.com/Maicy0609/HitSoundBench/issues/2) 指出的问题，
> 现在默认档改成"各自项目自己的 Release 档"，`uniform` 只作为对照保留。

- 两侧同一台机器、同一轮运行；`HITSOUNDBENCH_OPT` 记录在 `env.txt` 与报告里。
- 阶段耗时由 `src/probe.hpp` 记录（`steady_clock`），峰值内存取进程峰值 RSS
  （Linux `/proc/self/status` 的 `VmHWM`，Windows `GetProcessMemoryInfo`）。
- 两侧阶段划分不同，报告里逐行标注了口径（ADOCO 拆成 解析 / 角度传播+前缀和 / 混音 / 写盘；
  ADOFAI_HitSound 是 `load_adofai` + `generate` 两段）。不要跨行错位对比。
- 时间轴一致性用**按 tile 序号对齐**的逐 tile 差（`tile_diff.txt`）为准；
  「最近邻距离」在超密段落会失效（任何时间点都落在某个 hit 的几微秒内，测到的是网格密度）。

## 已知的、不是 bug 的差异

| 差异 | 原因 |
|---|---|
| 首击偏移：ADOCO 0 s，ref 0.6 s | ADOCO 的缓冲以「下标 0 = 第一次击打」对齐（前导静音交给播放器 pre-roll）；ref 直接输出含前导静音的整轨 |
| `level.zip` 那关 `hitsound` 是 `None` | 两侧仍用同一个 `hit.wav`：ADOCO 侧用上游自己的 `Timeline::setForceHitsoundType("Kick")`（等价于 CLI 的 `--force-hitsound`），ref 侧本来就只有一个样本 |
| 命中数：ADOCO 比 ref 多 4,988 个 | ref 的奈奎斯特过滤丢弃间隔 < 1/(sr/2) ≈ 41.7 µs 的重复 hit（Tempest 上正好 4,988 个，两边自报一致） |
| 整体增益差 | 两部分原因：(1) ADOCO 逐样本硬削波会顶到满量程，ref 按 1/√N 预缩放并把峰值留在 −14 dBFS；(2) 参考实现读的是 `settings["volume"]`（音乐音量）并强制 `max(v,100)`，而 ADOCO 正确读 `settings["hitsoundVolume"]` —— `levels/level.zip` 那关写着 `hitsoundVolume: 50`，于是两边天然差约 6 dB。这是字段读错的已知缺陷，不是失真 |
| 声道：2 vs 1 | ADOCO 输出立体声（L=R 复制），ref 输出单声道 |

## 实测结果（Actions run [36233904996](https://github.com/Maicy0609/HitSoundBench/actions/runs/36233904996)）

上游：ADOCAO `fe7cc1b` / ADOFAI_HitSound `2ed7892`；谱面 Tempest；打击音两侧同为 `hit.wav`；
两平台各自 3 次运行取最快（离散度 < 2%）。job 墙钟：ubuntu 67 s、windows 108 s。

| 阶段 (ms) | ubuntu-latest (GCC 13) | | windows-latest (MSVC 19.51) | |
|---|---:|---:|---:|---:|
| | ADOCAO | ADOFAI_HitSound | ADOCAO | ADOFAI_HitSound |
| 解析谱面 | 176.0 | 88.1 | 379.8 | 382.3 |
| 角度/BPM 传播 + 前缀和 | 6.6 | 含在上一行 | 17.3 | 含在上一行 |
| 合成 + 混音 | 3,147.1 | 524.0 | 4,287.0 | 907.6 |
| 写 WAV | 12.8 | 含在上一行 | 35.0 | 含在上一行 |
| **总计** | **3,366.7** | **612.1**（5.50×） | **4,782.7** | **1,289.9**（3.71×） |
| 峰值内存 (RSS) | 172.8 MB | 163.0 MB | 155.7 MB | 146.5 MB |

音频指标（采样率/声道、时长、峰值、RMS、削波、密度）与时间轴指标在两个平台上**完全一致**，
两侧输出 WAV 更是**逐字节相同**：

```
adocao.wav  sha256 a5ea3e77beb2c9221bfd20417d387fd8da8f9cb41ce945b3e51632751f34d1f5  (linux == windows)
ref.wav     sha256 c2d903ee5199e01cee8dfcee57238568bd891870739a06cea39d688abae23d4d  (linux == windows)
```

也就是说两套实现都是确定性流水线，平台之间只差耗时。

| 侧写 | ADOCAO | ADOFAI_HitSound |
|---|---|---|
| 时间轴 | 158,402 hits，逐击一致 | 153,414 hits（过滤掉 4,988 个重复），与 ADOCO 轴最大最近邻距离 0.021 ms = 1 采样 |
| 输出 | 149.186 s / 立体声（L=R） / 峰值 32,767 / RMS −7.06 dBFS | 138.786 s / 单声道 / 峰值 6,189 / RMS −29.83 dBFS |
| 削波 | 23,883 样本（0.334%）顶到满量程 | 0 |
| 包络动态范围 (P95−P5) | 5.96 dB | 12.25 dB |
| 最大同时发声数 | 973（含重复击打） | 879（过滤后） |
| 首击偏移 / 尾部静音 | 0 s / 11.0 s | 0.6 s（前导）/ 0 s |

### 结论

- **时间轴算法等价**：唯一的差别是 ref 的奈奎斯特过滤（丢弃间隔 < 41.7 µs 的重复 hit），
  其余逐击相同 —— 4,988 = 158,402 − 153,414，与 ref 自报的被过滤数完全相等。
- **性能**：ADOCO 慢 3.7×（MSVC）/ 5.5×（GCC）。原因在混音循环：ADOCO 每个样本做两次
  `clamp` 且写两声道、也没有先算密度；ref 每样本一次 `double` 累加，且用差分数组先求最大同时发声数。
- **音频**：ADOCO 是逐样本硬削波（密集段 0.334% 样本饱和，动态范围被压到 5.96 dB）；
  ref 是静态等功率预缩放 + 常数增益（0 削波、动态范围 12.25 dB），整体电平低约 23 dB
  —— 它另有可选的 EBU R128 后处理来补响度，因此**直接对放两个 `*.wav` 只能听出音量差**，
  要比音色请用增益对齐的 `ab_*.wav`。

> 本地沙箱（6 核容器）跑同一份代码：ADOCO 5,160 ms / ref 2,278 ms（2.27×）。
> 绝对值受容器 CPU 影响，只用来确认流程正确；正式数字以 Actions 为准。

## 目录

```
extract/          剥离脚本：extract.sh（取源）+ port_ref.py / patch_adocao.py（改写）+ shims/
src/              两侧的薄入口 adocao_gen / ref_main + 共用的指标采集 probe.hpp
tools/            analyze.py（报告与图表）+ audio_metrics.py（WAV/指标计算）
scripts/          run_bench.sh（本地与 CI 共用的唯一编排入口）
.github/workflows/bench.yml   手动触发的矩阵 workflow
```

## `levels/level.zip` 这个关卡（压测型）

体量：300 MB 的 `angleData`，**6,770,913 tiles / 206 秒音轨**；事件：6.15M 个 Twirl、
315 个 `SetSpeed`（`angleOffset` 全为 0）、22,005 个 999 中旋；`hitsound` 是 `None`、
`hitsoundVolume` 是 50。

它在两处把两套实现的差别**放大**了：

1. **奈奎斯特过滤**：命中平均间隔约 30 µs，小于 48 kHz 下的 `1/(sr/2)` = 41.7 µs，
   于是参考实现丢掉 **6,200,334 / 6,770,912（91.6%）** hit，只剩 570,578 个；
   ADOCO 不丢弃。所以那一栏"34× 慢"里，大部分来自"多处理了 12 倍的 hit"，
   按单个 hit 归一化后差距是 3~4 倍（Tempest 上也是 3~4 倍）。
2. **同一个 floor 上挂了两个 SetSpeed（`Bpm` + `Multiplier`）**：floor 27,473 就是这样，
   参考实现原来让乘数**覆盖**掉绝对 BPM，那一段的 BPM 因此比正确值高 4.5 倍，
   连续 26,256 个 tile 整体时长少 11.935 s（详见下文「时长差 11.9 s」一节）。
   同一关卡的 `angleData` 里还有 **111,785 个负数**和 **35,637 个 >360 的值**，
   暴露出另一个独立问题：参考实现当时对 `da` 只做一次 `if` 加减（不是取模），
   在这些取值上会算出异常旋转量 —— 这个也已修（改成 `fmod`），最小复现
   `[-112.5, 472.5, 0]`：旧版中间那一击直接消失、后面整体前移。

### 时长差 11.9 s 的定位与修复（`tile_diff.txt`）

`levels/level.zip` 那关：ADOCO 音轨 217.35 s / 参考实现 194.475 s。差别**不在尾巴**：

| 量 | 修复前 | 修复后 |
|---|---|---|
| 参考实现时间轴总长（`offsets_diag.txt`） | 194.2442 s | **206.1792 s**（= ADOCO 的 206.1192 s + 首 tile 0.06 s） |
| 逐 tile 总差（`tile_diff.txt`） | +11.9350 s | **-0.0000 s** |
| 逐 tile 差绝对值 | 中位 11,934.9989 ms | 中位 / P99 / 最大 均 ≤ 0.0011 ms |
| Tempest 回归对照 | — | 总差 +0.0000 s、逐 tile ≤ 0.0003 ms |

**根因不是旋转量，而是 BPM 事件被覆盖**：该关卡在 **floor 27,473** 上同时挂了两个 SetSpeed
（`Bpm 8000` 与 `Multiplier 2`）。参考实现原来用 `stdbpm = -bpmMultiplier` **覆盖写**，
于是绝对 BPM 8000 被丢掉、变成"上一 tile 的 BPM × 2"：

| | 段前 BPM | 段内 BPM | 段内每 tile 时长 |
|---|---:|---:|---:|
| ADOCO / 游戏口径（绝对 Bpm 打底，乘数叠加） | 36,000 | **16,000** = 8000×2 | 3.75 ms |
| 参考实现（旧） | 36,000 | **72,000** = 36,000×2 | 0.8333 ms |

倍数正好 4.5 = 36,000/8,000，与实测的段内时长比 **4.5005** 吻合；受影响的正是连续
**26,256 个 tile**（27,473 ~ 53,728，占 0.39%），其余 6,744,656 个 tile 逐 tile 差为 0。
修法一行：`t.stdbpm *= bpmMultiplier;`（同 floor 已有绝对 Bpm 时乘上去；同 floor 多个乘数连乘）。

> 顺带修正一个度量坑：报告里的「最近邻距离」在**超密段落**（命中间隔 5 µs 量级）会失效 ——
> 任何时间点都落在某个 hit 的几微秒内，测到的是网格密度而不是对齐程度，会掩盖这种全局偏移。
> **同长度的时间轴请以 `tile_diff.txt`（按 tile 序号对齐）为准。**

## 结果怎么解读

- **性能**：ADOCO 的混音循环每个样本要做两次 clamp（还写两声道），且没有先算密度；
  ref 每样本只做一次 double 累加，并用差分数组先求出最大同时发声数。差距主要来自这里。
- **音频**：ADR 方案（ADOCO）的密集段是硬削波饱和，ref 是常数增益 + 峰值安全余量。
  报告第 4 节给出各自的削波比例、包络动态范围，`ab_*.wav` 可以直接听出来。
- 想让两者响度真正可比，请用 `ab_*.wav`（增益对齐版），不要用两个 `*.wav` 直接对放。

## 关卡来源与解压

`LEVELS` 里 `level` 指向的 `levels/level.zip`（15.7 MB）**原样提交**，里面是一个解压后
315 MB 的 `level.adofai`；解压只发生在跑基准的时候（`scripts/run_bench.sh` 里的
`python -m zipfile -e`），解压产物落在 `build/levels/`，既不进版本库也不进产物。
`LEVEL_ZIP=<别的 zip>` 可以临时换成其它关卡包。

巨型关卡对分析侧的压力（几千万 hit、上 GB 波形）在实现上已经处理：

- hit 时间轴导出成**二进制 float64**（`.f64`，跑完立刻 gzip），不写成文本
- 同时发声密度用 `bincount` 差分，而不是 `np.add.at`（后者在千万级 hit 上慢一到两个数量级）
- 能量前缀和只算一次并被多处指标复用；A/B 稀疏段用包络上向量化地找"最安静的 10 s"，
  不存在按 hit 的 Python 循环
- 只保留最快一次的时间轴与 WAV（其余几次的 WAV 分析后即删），避免产物被撑爆
