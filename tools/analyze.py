#!/usr/bin/env python3
"""analyze.py —— 汇总一次基准跑分。

职责：挑出最快的一次运行 → 对齐两侧时间轴 → 算性能/音频/响度指标 →
产出 report.md（人看）、report.json（机器看）、compare.png（对比图）、
ab_*.wav（L=adocao / R=ref 的 A/B 试听片段）。所有数值计算都在 audio_metrics.py。

用法: analyze.py --out <out 目录> [--label <平台标签>] [--level-name <谱面名>]
"""
import argparse
import json
import pathlib
import re
import shutil
import sys

import numpy as np

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import audio_metrics as am  # noqa: E402

TOOLS = ("adocao", "ref")
TOOL_TITLE = {"adocao": "ADOCAO", "ref": "ADOFAI_HitSound"}
DENSE_SEC, SPARSE_SEC = 15.0, 10.0


# ── 读取 ─────────────────────────────────────────────────────────────────────
def read_kv(path):
    out = {}
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "=" in line:
            k, v = line.rsplit("=", 1)
            try:
                out[k.strip()] = float(v)
            except ValueError:
                pass
    return out


def pick_fastest(out_dir, tool):
    """在 metrics_<tool>.run<N>.txt 里挑 total_ms 最小的一次，把它固化为 <tool>.wav。

    同时清掉其余几次的 WAV：巨型关卡单个 WAV 可达数百 MB，留着会把产物撑爆。
    时间轴统一带扩展名复制（.txt 或 .txt.gz 原样保留），分析侧两种都能读。
    """
    runs = sorted(out_dir.glob(f"metrics_{tool}.run*.txt"))
    if not runs:
        sys.exit(f"[analyze] 找不到 {out_dir}/metrics_{tool}.run*.txt")
    best = min(runs, key=lambda p: read_kv(p).get("total_ms", float("inf")))
    run_id = re.search(r"run(\d+)", best.name).group(1)

    shutil.copy(best, out_dir / f"metrics_{tool}.txt")
    wav_src = out_dir / f"{tool}.run{run_id}.wav"
    shutil.copy(wav_src, out_dir / f"{tool}.wav")
    for p in out_dir.glob(f"{tool}.run*.wav"):
        p.unlink()

    timelines = sorted(out_dir.glob(f"timeline_{tool}.run{run_id}.*"))
    if timelines:
        # 从 "timeline_adocao.run1.f64.gz" 里取出 ".f64.gz" 作为规范名的后缀
        suffix = timelines[0].name.split(f".run{run_id}", 1)[1]
        shutil.copy(timelines[0], out_dir / f"timeline_{tool}{suffix}")

    # 其余几次的时间轴 dump 删掉：巨型关卡单个 dump 就有上百 MB
    for p in out_dir.glob(f"timeline_{tool}.run*"):
        if p.name != timelines[0].name:
            p.unlink()

    return run_id, read_kv(best)


class Track:
    """一个工具的输出：对齐到首击后的波形 + 时间轴 + 指标。

    巨型关卡下一个立体声 WAV 可到数百 MB，所以：mono 取连续副本、统计完立刻放掉
    原始多声道数组；能量前缀和只算一次，供多处指标复用。
    """

    def __init__(self, name, wav_path, timeline_path, hit_len_frames):
        self.name = name
        wav, self.sr = am.read_wav(wav_path)
        self.timeline = am.read_timeline(timeline_path)
        self.mono = np.ascontiguousarray(wav[:, 0])     # 连续副本，别持有整个立体声数组
        self.n_channels = int(wav.shape[1])
        self.first_hit = float(self.timeline[0]) if self.timeline.size else 0.0
        self.first_frame = int(round(self.first_hit * self.sr))
        self.rel_times = self.timeline - self.first_hit
        self.rel_frames = self.mono.size - self.first_frame

        self.prefix = am.loudness_prefix(self.mono) if self.mono.size else None
        self.summary = am.summarize(wav, self.sr, self.timeline, hit_len_frames,
                                    prefix=self.prefix)
        del wav
        self.per_hit_density, _ = am.density_curve(self.timeline, hit_len_frames, self.sr,
                                                  self.mono.size)

    def window(self, t_rel, dur_s):
        a = self.first_frame + int(round(t_rel * self.sr))
        b = min(self.mono.size, a + int(round(dur_s * self.sr)))
        return self.mono[max(0, a):b]


# ── 图表 ─────────────────────────────────────────────────────────────────────
def make_plot(out_dir, tracks, sparse_t, dense_t):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"adocao": "#d1495b", "ref": "#2e86ab"}
    fig, axes = plt.subplots(3, 1, figsize=(12, 11))

    # ① 全曲响度包络（命中相对时间）
    for name, tr in tracks.items():
        t, db = am.envelope_db(tr.mono[tr.first_frame:], tr.sr, 100)
        step = max(1, t.size // 4000)
        axes[0].plot(t[::step], np.maximum(db[::step], -80.0), color=colors[name], lw=0.7,
                     label=f"{name}  (peak {tr.summary['peak']}, clipped {tr.summary['clipped_pct']}%)")
    axes[0].set_title("Loudness envelope (100 ms RMS, dBFS) — aligned to first hit")
    axes[0].set_xlabel("seconds since first hit")
    axes[0].set_ylabel("dBFS")
    axes[0].set_ylim(-80, 2)      # 命中之间是真静音，不封顶会把整图压成一条线
    axes[0].legend(fontsize=8, loc="lower right")
    axes[0].grid(alpha=0.3)

    # ② / ③ 局部波形：稀疏段 / 最密段
    for ax, t0, title in ((axes[1], sparse_t, "Sparse section"),
                          (axes[2], dense_t, "Densest section")):
        for name, tr in tracks.items():
            seg = tr.window(t0, 1.5).astype(np.float64)
            ax.plot(np.arange(seg.size) / tr.sr + t0, seg, color=colors[name], lw=0.6,
                    label=f"{name}  (RMS {am.rms_db(seg):.1f} dBFS)")
        ax.set_title(f"{title}  @ {t0:.2f}s (1.5 s window)")
        ax.set_xlabel("seconds since first hit")
        ax.set_ylabel("amplitude")
        ax.legend(fontsize=8, loc="upper right")
        ax.grid(alpha=0.3)

    fig.tight_layout()
    fig.savefig(out_dir / "compare.png", dpi=110)
    plt.close(fig)


# ── 主流程 ───────────────────────────────────────────────────────────────────
def write_summary(out_root):
    """跨关卡汇总：读每个子目录的 report.json，出一张总表（out/summary.md）。"""
    rows = []
    for d in sorted(p for p in out_root.iterdir() if p.is_dir()):
        rj = d / "report.json"
        if not rj.exists():
            continue
        r = json.loads(rj.read_text(encoding="utf-8"))
        m, au, tl, loud = r["metrics"], r["audio"], r["timeline_diff"], r["loudness"]

        def g(dct, key, default=None):
            v = dct.get(key, default)
            return v if v is not None else default

        rows.append({
            "level": d.name,
            "tiles": int(m["adocao"].get("tiles") or 0),
            "hits": int(m["adocao"].get("hits") or 0),
            "adocao_ms": g(m["adocao"], "total_ms"),
            "ref_ms": g(m["ref"], "total_ms"),
            "adocao_mb": (g(m["adocao"], "peak_rss_kb", 0) or 0) / 1024.0,
            "ref_mb": (g(m["ref"], "peak_rss_kb", 0) or 0) / 1024.0,
            "max_dist_ms": g(tl, "ref_max_dist_ms"),
            "extra_hits": g(tl, "adocao_extra_hits"),
            "ref_hits": g(tl, "hits_ref"),
            "clipped_pct": g(au["adocao"], "clipped_pct", 0.0),
            "adocao_dyn": g(loud, "adocao_env_range_db"),
            "ref_dyn": g(loud, "ref_env_range_db"),
            "adocao_dur": g(au["adocao"], "duration_s", 0.0),
        })

    def fmt(v, nd=1, suffix=""):
        return "—" if v is None else f"{v:,.{nd}f}{suffix}"

    lines = [
        "# 跨关卡汇总",
        "",
        "| 关卡 | tiles | hits (ref) | ADOCO 总耗时 | ref 总耗时 | 倍数 | ADOCO 峰值内存 | ref 峰值内存 | 时间轴最大偏差 | 多出的 hit | ADOCO 削波 | 包络动态范围 (ADOCO / ref) |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        ratio = f"{r['adocao_ms'] / r['ref_ms']:.2f}x" if r["adocao_ms"] and r["ref_ms"] else "—"
        lines.append(
            f"| `{r['level']}` | {r['tiles']:,} | {r['ref_hits']:,} | {fmt(r['adocao_ms'], 0, ' ms')} "
            f"| {fmt(r['ref_ms'], 0, ' ms')} | {ratio} | {fmt(r['adocao_mb'], 1, ' MB')} "
            f"| {fmt(r['ref_mb'], 1, ' MB')} | {fmt(r['max_dist_ms'], 4, ' ms')} "
            f"| {r['extra_hits']:,} | {fmt(r['clipped_pct'], 3, ' %')} "
            f"| {fmt(r['adocao_dyn'], 2)} / {fmt(r['ref_dyn'], 2)} dB |")
    md = "\n".join(lines) + "\n"
    (out_root / "summary.md").write_text(md, encoding="utf-8")
    print(md)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, help="单个关卡的输出目录（生成报告）")
    ap.add_argument("--summary", type=pathlib.Path, help="跨关卡汇总：读各子目录的 report.json")
    ap.add_argument("--label", default="local")
    ap.add_argument("--level-name", default="level")
    args = ap.parse_args()
    if args.summary:
        write_summary(args.summary)
        return
    if not args.out:
        ap.error("需要 --out（或 --summary）")
    out = args.out

    provenance = (out / "PROVENANCE.txt").read_text(encoding="utf-8", errors="replace") \
        if (out / "PROVENANCE.txt").exists() else ""
    env = (out / "env.txt").read_text(encoding="utf-8", errors="replace") \
        if (out / "env.txt").exists() else ""

    hit_wav, hit_sr = am.read_wav(out / "assets" / "hit.wav")
    hit_frames = hit_wav.shape[0]

    metrics, run_ids, tracks = {}, {}, {}
    for tool in TOOLS:
        run_id, kv = pick_fastest(out, tool)
        metrics[tool], run_ids[tool] = kv, run_id
        tl = next(p for p in (out / f"timeline_{tool}.f64", out / f"timeline_{tool}.f64.gz",
                              out / f"timeline_{tool}.txt", out / f"timeline_{tool}.txt.gz")
                  if p.exists())
        tracks[tool] = Track(tool, out / f"{tool}.wav", tl, hit_frames)
    a, b = tracks["adocao"], tracks["ref"]
    n_runs = len(list(out.glob("metrics_adocao.run*.txt")))

    # ── 时间轴对齐比较 ──
    # 两侧命中集合不同（ref 会丢掉奈奎斯特过滤掉的重复 hit），逐下标比较会整体错位，
    # 因此改用最近邻匹配：每个 ref hit 到 ADOCAO 时间轴的最近距离，以及反向的「无对应」数。
    TOL = 5e-4  # 0.5 ms 内视为同一击

    def nearest(src, dst):
        if src.size == 0 or dst.size == 0:
            return np.zeros(0)
        i = np.clip(np.searchsorted(dst, src), 0, dst.size - 1)
        j = np.clip(i - 1, 0, dst.size - 1)
        return np.minimum(np.abs(src - dst[i]), np.abs(src - dst[j]))

    fwd = nearest(b.rel_times, a.rel_times)          # ref → adocao
    back = nearest(a.rel_times, b.rel_times)         # adocao → ref
    matched = fwd <= TOL
    timeline = {
        "hits_adocao": int(a.rel_times.size),
        "hits_ref": int(b.rel_times.size),
        "ref_hits_matched": int(np.count_nonzero(matched)),
        "ref_max_dist_ms": round(float(fwd.max() * 1e3), 4) if fwd.size else None,
        "ref_median_dist_ms": round(float(np.median(fwd) * 1e3), 4) if fwd.size else None,
        "ref_p99_dist_ms": round(float(np.percentile(fwd, 99) * 1e3), 4) if fwd.size else None,
        "worst_at_s": round(float(b.rel_times[int(np.argmax(fwd))]), 4) if fwd.size else None,
        "adocao_extra_hits": int(a.rel_times.size - b.rel_times.size),
        "adocao_to_ref_max_dist_ms": round(float(back.max() * 1e3), 4) if back.size else None,
        "adocao_to_ref_median_dist_ms": round(float(np.median(back) * 1e3), 4) if back.size else None,
        "adocao_to_ref_p99_dist_ms": round(float(np.percentile(back, 99) * 1e3), 4) if back.size else None,
        "first_hit_offset_adocao_s": round(a.first_hit, 4),
        "first_hit_offset_ref_s": round(b.first_hit, 4),
    }
    ref_filtered = re.search(r"after Nyquist filter: (\d+) hits \((\d+) removed\)",
                             (out / f"log_ref.run{run_ids['ref']}.txt").read_text(
                                 encoding="utf-8", errors="replace")).group(2) \
        if (out / f"log_ref.run{run_ids['ref']}.txt").exists() else None
    timeline["ref_filtered_reported"] = int(ref_filtered) if ref_filtered else None

    # ── 响度动态：常数增益（等功率预缩放）vs 逐样本硬削波 ──
    # 注意两侧命中集合不同（ref 丢弃了奈奎斯特过滤掉的 hit），掩码必须各算各的。
    dens = a.per_hit_density                       # 仅用于挑稀疏/密集区间（时间轴对齐）
    loud = {}
    for tool, tr in (("adocao", a), ("ref", b)):
        d = tr.per_hit_density
        solo = d == 1
        dense = d >= max(2, int(np.percentile(d, 99))) if d.size else None
        loud[f"{tool}_solo_hits"] = int(np.count_nonzero(solo))
        loud[f"{tool}_dense_threshold"] = int(d[dense].min()) if dense is not None and dense.any() else None
        loud[f"{tool}_solo_db"] = round(am.median_rms_db(tr.mono, tr.sr, tr.timeline, solo,
                                                         prefix=tr.prefix), 2) if solo.any() else None
        loud[f"{tool}_dense_db"] = round(am.median_rms_db(tr.mono, tr.sr, tr.timeline, dense,
                                                          prefix=tr.prefix), 2) \
            if dense is not None and dense.any() else None
        s, dd = loud[f"{tool}_solo_db"], loud[f"{tool}_dense_db"]
        loud[f"{tool}_dynamic_db"] = round(dd - s, 2) if s is not None and dd is not None else None
        # 全曲包络动态范围（比 solo/密集 更稳，尤其当谱面几乎没有单独发声的 hit）
        _, env_curve = am.envelope_db(tr.mono[tr.first_frame:], tr.sr, 100)
        active = env_curve[env_curve > -60.0]
        if active.size:
            p5, p95 = np.percentile(active, [5, 95])
            loud[f"{tool}_env_p5_db"] = round(float(p5), 2)
            loud[f"{tool}_env_p95_db"] = round(float(p95), 2)
            loud[f"{tool}_env_range_db"] = round(float(p95 - p5), 2)

    # ── A/B 试听（L=adocao，R=ref，同一段区间）──
    # 稀疏段取「全曲最安静的 10 s」（包络上向量化求解），密集段取最密那一击附近。
    common_rel = min(a.rel_frames, b.rel_frames) / a.sr
    dense_t = max(0.0, float(a.rel_times[int(np.argmax(dens))]) - 0.2) if dens.size else 0.0
    sparse_t = min(am.quietest_window_start(a.mono[a.first_frame:], a.sr, SPARSE_SEC),
                   max(0.0, common_rel - SPARSE_SEC))
    for tag, t0, dur in (("sparse", sparse_t, SPARSE_SEC), ("dense", dense_t, DENSE_SEC)):
        dur = min(dur, max(0.5, common_rel - t0))
        left, right = a.window(t0, dur), b.window(t0, dur)
        # 增益对齐版（听感公平）+ 原始电平版（数值诚实）
        am.write_wav(out / f"ab_{tag}.wav", a.sr,
                     am.ab_join(am.normalize_rms(left), am.normalize_rms(right)))
        am.write_wav(out / f"ab_{tag}_raw.wav", a.sr, am.ab_join(left, right))

    make_plot(out, tracks, sparse_t, dense_t)

    # ── 报告 ──
    def get(key, tool):
        v = metrics[tool].get(key)
        return None if v is None else float(v)

    def ms(key, tool):
        v = get(key, tool)
        return "—" if v is None else f"{v:,.1f}"

    def mb(key, tool):
        v = get(key, tool)
        return "—" if v is None else f"{v / 1024:,.1f} MB"

    def fmt(v, suffix="", nd=2):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return "—"
        return f"{v:,.{nd}f}{suffix}" if isinstance(v, (int, float)) else f"{v}{suffix}"

    a_total, r_total = get("total_ms", "adocao"), get("total_ms", "ref")
    speed = f"（ADOCO 是 ref 的 {a_total / r_total:.2f}×）" if a_total and r_total else ""
    perf_rows = "\n".join([
        f"| 解析谱面 | {ms('load_ms', 'adocao')} | {ms('load_ms', 'ref')}（`load_adofai` 含 Tile::update 链式累积） |",
        f"| 角度/BPM 传播 + 前缀和 | {ms('timeline_ms', 'adocao')} | 含在上一行 |",
        f"| 合成 + 混音 | {ms('synthesize_ms', 'adocao')} | {ms('generate_ms', 'ref')}（含奈奎斯特滤波 + 密度统计 + 写盘） |",
        f"| 写 WAV | {ms('write_wav_ms', 'adocao')} | 含在上一行 |",
        f"| **总计** | **{ms('total_ms', 'adocao')}** | **{ms('total_ms', 'ref')}** {speed} |",
        f"| 峰值内存 (RSS) | {mb('peak_rss_kb', 'adocao')} | {mb('peak_rss_kb', 'ref')} |",
    ])

    audio_rows = "\n".join([
        f"| 采样率 / 声道 | {int(a.summary['sample_rate']):,} Hz / {a.summary['channels']} | "
        f"{int(b.summary['sample_rate']):,} Hz / {b.summary['channels']} |",
        f"| 帧数 / 时长 | {a.summary['frames']:,} / {fmt(a.summary['duration_s'], ' s', 3)} | "
        f"{b.summary['frames']:,} / {fmt(b.summary['duration_s'], ' s', 3)} |",
        f"| 首击偏移 / 尾部静音 | {fmt(a.summary['first_hit_s'], ' s', 3)} / {fmt(a.summary['trailing_silence_s'], ' s', 3)} | "
        f"{fmt(b.summary['first_hit_s'], ' s', 3)} / {fmt(b.summary['trailing_silence_s'], ' s', 3)} |",
        f"| 峰值 (int16) | {a.summary['peak']:,} | {b.summary['peak']:,} |",
        f"| 整体 RMS | {fmt(a.summary['rms_db'], ' dBFS')} | {fmt(b.summary['rms_db'], ' dBFS')} |",
        f"| 削波样本数 / 占比 | {a.summary['clipped_samples']:,} / {fmt(a.summary['clipped_pct'], ' %', 3)} | "
        f"{b.summary['clipped_samples']:,} / {fmt(b.summary['clipped_pct'], ' %', 3)} |",
        f"| DC 偏置 | {a.summary['dc_offset']} | {b.summary['dc_offset']} |",
        f"| 最大同时发声数 | {a.summary['max_density']:,} | {b.summary['max_density']:,} |",
        f"| 两声道是否相同 | {'是（单声道复制）' if a.summary['channels_identical'] else '否'} | "
        f"{'是' if b.summary['channels_identical'] else '否（单声道）'} |",
    ])

    loud_rows = "\n".join([
        f"| 单独发声命中处的中位 RMS | {fmt(loud['adocao_solo_db'], ' dBFS')}（{loud['adocao_solo_hits']:,} 个） | "
        f"{fmt(loud['ref_solo_db'], ' dBFS')}（{loud['ref_solo_hits']:,} 个） |",
        f"| 密集段（同时发声 ≥ {loud['adocao_dense_threshold']}）中位 RMS | {fmt(loud['adocao_dense_db'], ' dBFS')} | "
        f"{fmt(loud['ref_dense_db'], ' dBFS')} |",
        f"| **同轨动态范围（密集 − 稀疏）** | {fmt(loud['adocao_dynamic_db'], ' dB')} | "
        f"{fmt(loud['ref_dynamic_db'], ' dB')} |",
        f"| 全曲包络 P5 / P95 | {fmt(loud.get('adocao_env_p5_db'), ' / ')}{fmt(loud.get('adocao_env_p95_db'), ' dBFS')} | "
        f"{fmt(loud.get('ref_env_p5_db'), ' / ')}{fmt(loud.get('ref_env_p95_db'), ' dBFS')} |",
        f"| 包络动态范围 (P95−P5) | {fmt(loud.get('adocao_env_range_db'), ' dB')} | "
        f"{fmt(loud.get('ref_env_range_db'), ' dB')} |",
    ])

    md = f"""# HitSound 基准：ADOCAO vs ADOFAI_HitSound

- 平台：`{args.label}`　运行 {n_runs} 次（选用了第 {run_ids['adocao']} / {run_ids['ref']} 次，依据 `total_ms` 最小）
- 谱面：`{args.level_name}` —— {int(metrics['adocao'].get('tiles') or 0):,} tiles / {a.summary['hits']:,} hits
- 打击音：**两侧同一个样本**（ADOFAI_HitSound 的 `hit.wav`，{hit_frames:,} 帧 @ {hit_sr} Hz）
- 每工具各次运行的原始指标见 `metrics_*.run*.txt`，完整日志见 `log_*.txt`

## 1. 性能（同机同谱面、同为 -O2，未开 -march=native）

| 阶段 (ms) | ADOCAO | ADOFAI_HitSound |
|---|---:|---|
{perf_rows}

- 两侧阶段口径不同，逐行看：ADOCO 把「解析 / 角度传播 + 前缀和 / 混音 / 写盘」分开计时；
  ADOFAI_HitSound 是 `load_adofai`（解析 + `Tile::update` 累积）与 `generate`（滤波 + 密度 + 混音 + 写盘）两段。
- 输出规模不同：ADOCO {a.summary['frames']:,} 帧 × {a.summary['channels']} 声道；ref {b.summary['frames']:,} 帧 × {b.summary['channels']} 声道。

## 2. 时间轴一致性（各自去掉首击偏移后，最近邻匹配）

| 指标 | 值 |
|---|---:|
| hit 数（ADOCO / ref） | {timeline['hits_adocao']:,} / {timeline['hits_ref']:,} |
| ref 的 hit 能在 ADOCO 轴 0.5 ms 内找到对应的 | {timeline['ref_hits_matched']:,} / {timeline['hits_ref']:,} |
| ref→ADOCO 最近邻距离：最大 / 中位 / P99 | {fmt(timeline['ref_max_dist_ms'], ' ms', 4)} / {fmt(timeline['ref_median_dist_ms'], ' ms', 4)} / {fmt(timeline['ref_p99_dist_ms'], ' ms', 4)} |
| 最大距离出现于 | {fmt(timeline['worst_at_s'], ' s（命中相对时间）', 3)} |
| ADOCO→ref 最近邻距离：最大 / 中位 / P99 | {fmt(timeline['adocao_to_ref_max_dist_ms'], ' ms', 4)} / {fmt(timeline['adocao_to_ref_median_dist_ms'], ' ms', 4)} / {fmt(timeline['adocao_to_ref_p99_dist_ms'], ' ms', 4)} |
| ADOCO 比 ref 多出的 hit | {timeline['adocao_extra_hits']:,} 个（ref 自报被过滤 {timeline['ref_filtered_reported'] if timeline['ref_filtered_reported'] is not None else '—'}） |
| 首击绝对偏移（ADOCO / ref） | {fmt(timeline['first_hit_offset_adocao_s'], ' s', 3)} / {fmt(timeline['first_hit_offset_ref_s'], ' s', 3)} |

> - 首击偏移不同不是 bug：ADOCO 的音频缓冲以「下标 0 = 第一次击打」对齐（前导静音交给播放器的
>   pre-roll），ADOFAI_HitSound 直接输出含前导静音的整轨。
> - 命中数差 = ref 侧奈奎斯特过滤丢弃的重复 hit（间隔 < 1/(sr/2) = 41.7 µs）：若「多出的 hit 数」
>   与 ref 自报的被过滤数相等，且两个方向的最近邻距离都在一个采样（≈21 µs）量级，就说明
>   两套时间轴逐击一致，差异只来自这条滤波规则。

## 3. 音频指标

| 指标 | ADOCAO | ADOFAI_HitSound |
|---|---:|---:|
{audio_rows}

## 4. 响度动态

| 指标 | ADOCAO | ADOFAI_HitSound |
|---|---:|---:|
{loud_rows}

试听 `ab_sparse.wav` / `ab_dense.wav`：**左耳 ADOCO、右耳 ADOFAI_HitSound**，同一区间，两条声道各自归一到 −20 dBFS RMS
（原始电平版见 `ab_*_raw.wav`：ADOCO 整体 {fmt(a.summary['rms_db'], ' dBFS')} / ref {fmt(b.summary['rms_db'], ' dBFS')}，
差 {fmt((b.summary['rms_db'] or 0) - (a.summary['rms_db'] or 0), ' dB')} —— 这是设计差异，不是失真）。

## 5. 产物

- `adocao.wav` / `ref.wav`：两侧原始输出（未剪辑）
- `ab_sparse.wav` / `ab_dense.wav`：A/B 试听片段（增益对齐）
- `ab_*_raw.wav`：A/B 片段的原始电平版
- `timeline_*.f64.gz`：hit 时间轴（二进制 float64，巨型关卡下比文本省一个量级）
- `metrics_*.txt` / `log_*.txt`：每次运行的原始指标与日志（每次运行都留）

## 6. 溯源与运行环境

```
{provenance.strip()}
{env.strip()}
```
"""
    (out / "report.md").write_text(md, encoding="utf-8")
    (out / "report.json").write_text(json.dumps({
        "label": args.label,
        "level": args.level_name,
        "runs": n_runs,
        "runs_selected": run_ids,
        "metrics": metrics,
        "audio": {t: tracks[t].summary for t in TOOLS},
        "timeline_diff": timeline,
        "loudness": loud,
        "env": env.strip().splitlines(),
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    print(md)
    print(f"[analyze] 报告已写入 {out}/report.md, report.json, compare.png, ab_*.wav")


if __name__ == "__main__":
    main()
