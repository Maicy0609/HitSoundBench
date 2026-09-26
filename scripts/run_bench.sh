#!/usr/bin/env bash
# run_bench.sh —— 一次完整基准：剥离上游 → 构建 → 跑 N 次 → 出报告。
#
# 本地与 CI 共用这一个入口（不做重复的编排逻辑）。
# 用法：
#   scripts/run_bench.sh                      # 默认 3 次，从 GitHub 取上游
#   RUNS=5 LABEL=ubuntu-latest scripts/run_bench.sh
#   ADOCAO_SRC=/path/to/ADOCAO HITSOUND_SRC=/path/to/ADOFAI_HitSound scripts/run_bench.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS="${RUNS:-3}"
PY="${PY:-$(command -v python3 || command -v python)}"
BUILD="$ROOT/build"
OUT="$ROOT/out"
EX="$BUILD/extracted"

step() { printf '\n▸ %s\n' "$*"; }
exe() { # 找可执行文件：build/、build/*.exe、build/Release/*.exe（多配置生成器的兜底）
    for cand in "$BUILD/$1" "$BUILD/$1.exe" "$BUILD/Release/$1.exe" "$BUILD/Release/$1"; do
        [ -f "$cand" ] && { printf '%s' "$cand"; return; }
    done
    echo "❌ 找不到可执行文件 $1" >&2; exit 1
}

rm -rf "$OUT"; mkdir -p "$OUT"

step "① 剥离上游源码（不保存代码副本，每次现取现剥离）"
bash "$ROOT/extract/extract.sh"
cp "$EX/PROVENANCE.txt" "$OUT/PROVENANCE.txt"

step "② 环境信息"
{
    "$PY" - <<'PY'
import multiprocessing, platform
print("platform       " + platform.platform())
print("machine        " + platform.machine())
print("cpu            " + (platform.processor() or "unknown"))
print("cores          " + str(multiprocessing.cpu_count()))
PY
    cmake --version | head -1
    { cc --version 2>/dev/null | head -1; } || true
    { cl 2>&1 | head -1; } || true
} | tee "$OUT/env.txt"

step "③ 配置 / 构建（两侧同为 Release、O2，不开 -march=native）"
GEN=""
command -v ninja >/dev/null 2>&1 && GEN="-G Ninja"
cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release $GEN
cmake --build "$BUILD" --parallel

ADOCAO_EXE="$(exe adocao_gen)"
REF_EXE="$(exe ref_gen)"
LEVEL="$EX/assets/Tempest.adofai"
HIT_WAV="$EX/assets/hit.wav"

# 两侧必须用同一个打击音样本：ref 直接读 hit.wav；ADOCO 按谱面 hitsound 类型
# （Tempest 是 "Kick"）去资源目录取 Kick.wav，故放一份同内容文件。
mkdir -p "$OUT/assets"
cp "$HIT_WAV" "$OUT/assets/hit.wav"
cp "$HIT_WAV" "$OUT/assets/Kick.wav"

for i in $(seq 1 "$RUNS"); do
    step "④ 第 $i/$RUNS 次：ADOCO"
    ( cd "$OUT" && "$ADOCAO_EXE" "$LEVEL" "$OUT/assets" "$OUT/adocao.run$i.wav" \
        "$OUT/metrics_adocao.run$i.txt" "$OUT/timeline_adocao.run$i.txt" ) \
        2>&1 | tee "$OUT/log_adocao.run$i.txt"

    step "④ 第 $i/$RUNS 次：ADOFAI_HitSound"
    ( cd "$OUT" && "$REF_EXE" "$LEVEL" "$HIT_WAV" "$OUT/ref.run$i.wav" \
        "$OUT/metrics_ref.run$i.txt" "$OUT/timeline_ref.run$i.txt" ) \
        2>&1 | tee "$OUT/log_ref.run$i.txt"
done

step "⑤ 分析（挑最快一次 → 对齐时间轴 → 响度/音频指标 → 图表 / A-B 片段）"
"$PY" "$ROOT/tools/analyze.py" --out "$OUT" --label "${LABEL:-$(uname -s -m)}" \
    --level-name "$(basename "$LEVEL")"
