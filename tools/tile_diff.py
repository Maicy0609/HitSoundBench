#!/usr/bin/env python3
"""tile_diff.py —— 按 tile 序号对齐，比较参考实现的累计时间与 ADOCO 的 hit 时间。

回答「两条时间轴总长为什么不同、差在哪一段」：
两边的第 i 个值都对应同一个 tile（参考实现的 tiles[i].offset 与 ADOCO 的第 i 个 hit），
所以可以逐 tile 相减，看差值在哪一段被拉开，并统计每段贡献了多少秒。

用法: tile_diff.py <offsets_ref.f64|.gz> <timeline_adocao.f64.gz|.f64> [--top N]
"""
import argparse
import gzip
import pathlib

import numpy as np


def load(path):
    p = pathlib.Path(path)
    if not p.exists():
        raise SystemExit(f"[tile_diff] 找不到 {p}")
    buf = gzip.open(p, "rb").read() if p.suffix == ".gz" else p.read_bytes()
    return np.frombuffer(buf, dtype="<f8").astype(np.float64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("offsets_ref")
    ap.add_argument("timeline_adocao")
    ap.add_argument("--top", type=int, default=10)
    ap.add_argument("--bucket", type=float, default=10.0, help="分段长度（秒，按参考实现时间切）")
    args = ap.parse_args()

    ref = load(args.offsets_ref)
    ado = load(args.timeline_adocao)
    # 对齐：参考实现的 offsets 含 tile 0（offset = 0），而 ADOCO 的时间轴是从 tile 1 开始的
    # hit 序列；所以丢掉参考实现的第一项，让第 i 项都对应同一个 tile。
    if ref.size == ado.size + 1:
        ref = ref[1:]
    n = min(ref.size, ado.size)
    if ref.size != ado.size:
        print(f"注意：长度不同（参考实现 {ref.size:,} 个 tile / ADOCO {ado.size:,} 个 hit），"
              f"只比较前 {n:,} 个")
    ref, ado = ref[:n], ado[:n]

    diff = ado - ref                                    # >0 表示 ADOCO 更晚
    delta = np.diff(diff, prepend=0.0)                  # 每个 tile 的时长差
    print(f"tiles 比较数        = {n:,}")
    print(f"参考实现末值        = {ref[-1]:.4f} s")
    print(f"ADOCO 末值          = {ado[-1]:.4f} s")
    print(f"总差（ADOCO − ref） = {diff[-1]:+.4f} s")
    print(f"逐 tile 差绝对值：中位 {np.median(np.abs(diff)) * 1e3:.4f} ms  "
          f"P99 {np.percentile(np.abs(diff), 99) * 1e3:.4f} ms  "
          f"最大 {np.abs(diff).max() * 1e3:.4f} ms")

    # 按参考实现的时间轴分桶，统计每桶里「时长差」的净和（= 这一段丢/多了多少时间）
    contrib, i = [], 0
    while i < n:
        j = max(i + 1, int(np.searchsorted(ref, ref[i] + args.bucket, side="right")))
        j = min(j, n)
        contrib.append((float(ref[i]), float(ref[j - 1]), float(delta[i:j].sum())))
        i = j
    contrib.sort(key=lambda x: -abs(x[2]))
    print(f"\n贡献最大的 {args.top} 段（按参考实现时间每 {args.bucket:.0f} s 一段）：")
    print("   起点(s)     终点(s)      该段净差(s)")
    for lo, hi, c in contrib[: args.top]:
        print(f"  {lo:9.3f}  {hi:9.3f}   {c:+12.4f}")

    nz = np.abs(delta) > 1e-6
    print(f"\n逐 tile 时长有差异的 tile 数 = {int(nz.sum()):,}（占 {100 * nz.sum() / n:.2f}%）")
    if nz.any():
        k = int(np.argmax(np.abs(delta)))
        print(f"单 tile 时长差最大处：tile {k:,}（参考时间 {ref[k]:.4f} s），差 {delta[k] * 1e3:+.4f} ms")
        print(f"这些 tile 的累计贡献：正 {delta[delta > 0].sum():+.4f} s / "
              f"负 {delta[delta < 0].sum():+.4f} s")


if __name__ == "__main__":
    main()
