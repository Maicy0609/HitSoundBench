#!/usr/bin/env python3
"""audio_metrics.py —— WAV 读写 + 音频指标 + A/B 拼接。

唯一职责：把 WAV/时间轴变成数字，不负责排版和画图（那是 analyze.py 的事）。
只用 numpy + 标准库 wave，不引入额外音频依赖。
"""
import wave

import numpy as np

FULL_SCALE = 32768.0
CLIP_LEVEL = 32767


# ── I/O ──────────────────────────────────────────────────────────────────────
def read_wav(path):
    """返回 (int16 [frames, channels], sample_rate)。"""
    with wave.open(str(path), "rb") as w:
        ch, sr, width, n = w.getnchannels(), w.getframerate(), w.getsampwidth(), w.getnframes()
        raw = w.readframes(n)
    if width != 2:
        raise ValueError(f"{path}: 只支持 16-bit PCM（实际 {width * 8} bit）")
    return np.frombuffer(raw, dtype="<i2").reshape(-1, ch), sr


def write_wav(path, sr, data):
    """data: [frames, channels] int16。"""
    data = np.ascontiguousarray(np.clip(data, -FULL_SCALE, CLIP_LEVEL).astype("<i2"))
    with wave.open(str(path), "wb") as w:
        w.setnchannels(data.shape[1])
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(data.tobytes())


def read_timeline(path):
    return np.atleast_1d(np.loadtxt(str(path), dtype=np.float64))


# ── 采样级指标 ───────────────────────────────────────────────────────────────
def rms_db(x):
    if x.size == 0:
        return float("-inf")
    r = float(np.sqrt(np.mean(np.square(x.astype(np.float64))))) / FULL_SCALE
    return 20.0 * np.log10(max(r, 1e-12))


def peak(x):
    return int(np.abs(x).max()) if x.size else 0


def clipped_samples(x):
    return int(np.count_nonzero(np.abs(x) >= CLIP_LEVEL))


def envelope_db(x, sr, win_ms=50):
    """滑窗 RMS 包络（dBFS），返回 (窗口中心秒, dB)。"""
    win = max(1, int(sr * win_ms / 1000.0))
    n = x.size // win
    if n == 0:
        return np.zeros(0), np.zeros(0)
    frames = x[: n * win].astype(np.float64).reshape(n, win)
    rms = np.sqrt(np.mean(np.square(frames), axis=1)) / FULL_SCALE
    times = (np.arange(n) + 0.5) * win / sr
    return times, 20.0 * np.log10(np.maximum(rms, 1e-12))


# ── 同时发声密度 ─────────────────────────────────────────────────────────────
def density_curve(hit_times, hit_len_frames, sr, n_samples):
    """返回 (每个 hit 起始处的同时发声数, 整段的最大同时发声数)。"""
    if hit_times.size == 0:
        return np.zeros(0, dtype=np.int32), 0
    starts = np.rint(hit_times * sr).astype(np.int64)
    np.clip(starts, 0, n_samples - 1, out=starts)
    ends = np.minimum(starts + hit_len_frames, n_samples)
    diff = np.zeros(n_samples + 1, dtype=np.int32)
    np.add.at(diff, starts, 1)
    np.add.at(diff, ends, -1)
    dens = np.cumsum(diff)[:-1]
    return dens[starts], int(dens.max()) if dens.size else 0


def window_rms_db(x, sr, center_s, half_ms=25):
    a = int(max(0, (center_s - half_ms / 1000.0) * sr))
    b = int(min(x.size, (center_s + half_ms / 1000.0) * sr))
    return rms_db(x[a:b])


def median_rms_db(x, sr, hit_times, mask, half_ms=25):
    """命中起始处 ±half_ms 窗口 RMS 的中位数（dBFS）。

    用前缀平方和做积分图，一次向量化算完 15 万个窗口（逐窗口切片太慢）。
    """
    if mask is None or not np.any(mask):
        return float("nan")
    cs = np.concatenate(([0.0], np.cumsum(x.astype(np.float64) ** 2)))
    half = max(1, int(half_ms / 1000.0 * sr))
    centers = np.rint(hit_times[mask] * sr).astype(np.int64)
    lo = np.clip(centers - half, 0, x.size - 1)
    hi = np.clip(centers + half + 1, 1, x.size)
    mean_square = (cs[hi] - cs[lo]) / np.maximum(hi - lo, 1)
    return float(np.median(10.0 * np.log10(np.maximum(mean_square, 1e-24) / (FULL_SCALE ** 2))))


# ── 报告里用到的汇总 ─────────────────────────────────────────────────────────
def summarize(x, sr, hit_times, hit_len_frames):
    """x: [frames, channels] int16（多声道时以第 0 声道为准做统计）。"""
    mono = x[:, 0]
    last_end = int(round(hit_times[-1] * sr)) + hit_len_frames if hit_times.size else 0
    per_hit_density, max_density = density_curve(hit_times, hit_len_frames, sr, mono.size)
    solo = per_hit_density == 1
    dense = per_hit_density >= max(2, int(np.percentile(per_hit_density, 99))) if per_hit_density.size else None
    return {
        "frames": int(x.shape[0]),
        "channels": int(x.shape[1]),
        "sample_rate": int(sr),
        "duration_s": round(x.shape[0] / sr, 3),
        "channels_identical": bool(x.shape[1] > 1 and np.array_equal(x[:, 0], x[:, 1])),
        "peak": peak(mono),
        "rms_db": round(rms_db(mono), 2),
        "clipped_samples": clipped_samples(mono),
        "clipped_pct": round(100.0 * clipped_samples(mono) / max(1, mono.size), 3),
        "dc_offset": round(float(mono.mean()) / FULL_SCALE, 6),
        "hits": int(hit_times.size),
        "first_hit_s": round(float(hit_times[0]), 6) if hit_times.size else None,
        "last_hit_s": round(float(hit_times[-1]), 6) if hit_times.size else None,
        "trailing_silence_s": round(max(0, mono.size - last_end) / sr, 3),
        "hit_len_frames": int(hit_len_frames),
        "max_density": max_density,
        "solo_hits": int(np.count_nonzero(solo)) if per_hit_density.size else 0,
        "solo_rms_db": round(median_rms_db(mono, sr, hit_times, solo), 2) if per_hit_density.size else None,
        "dense_rms_db": round(median_rms_db(mono, sr, hit_times, dense), 2) if per_hit_density.size else None,
    }


def ab_join(a_left, b_right):
    """把两个单声道拼成 L/R 立体声（同一个区间，用来 A/B 听同一段）。"""
    n = min(a_left.shape[0], b_right.shape[0])
    return np.stack([a_left[:n], b_right[:n]], axis=1)


def normalize_rms(x, target_db=-20.0):
    """把一段音频的整体 RMS 归一到 target_db（dBFS）。

    两侧输出的整体增益本来就不一样（ADOCO 逐样本硬削波顶到满量程、ref 留了约 14 dB 余量），
    直接并列试听会只听到「谁更响」。A/B 片段做增益对齐，原始电平另存一份。
    """
    rms = np.sqrt(np.mean((x.astype(np.float64) / FULL_SCALE) ** 2))
    if rms <= 1e-12:
        return x
    gain = (10.0 ** (target_db / 20.0)) / rms
    return np.clip(x.astype(np.float64) * gain, -FULL_SCALE, CLIP_LEVEL).astype("<i2")


def longest_low_density_window(hit_times, per_hit_density, start_s, end_s, max_density, min_len_s):
    """在 [start_s, end_s) 里找一段长度 ≥ min_len_s、同时发声数 ≤ max_density 的区间。"""
    if hit_times.size == 0:
        return None
    sel = (hit_times >= start_s) & (hit_times < end_s - min_len_s)
    idx = np.flatnonzero(sel & (per_hit_density <= max_density))
    for i in idx:
        t0 = hit_times[i]
        nxt = hit_times[(hit_times >= t0) & (hit_times < t0 + min_len_s)]
        pos = np.searchsorted(hit_times, t0)
        window = per_hit_density[pos : pos + nxt.size] if nxt.size else np.zeros(0)
        if window.size and int(window.max()) <= max_density and t0 + min_len_s <= end_s:
            return float(t0)
    return None
