#!/usr/bin/env bash
# run_bench.sh —— 完整基准：剥离上游 → 构建 → 逐关卡跑 N 次 → 出报告（本地与 CI 共用）。
#
# 关卡由 LEVELS 指定（逗号分隔）：
#   tempest —— 上游 ADOFAI_HitSound 仓库里的 x64/Release/Tempest.adofai（158k tiles）
#   level   —— 本仓库 levels/level.zip 里的 level.adofai（315 MB 的巨型关卡）
#              压缩包原样提交，**只在跑的时候解压**，解压产物不进版本库
#   <路径>  —— 直接当 .adofai 路径处理
#
# 用法：
#   RUNS=3 scripts/run_bench.sh
#   RUNS=1 LEVELS=level scripts/run_bench.sh
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNS="${RUNS:-3}"
LEVELS="${LEVELS:-tempest,level}"
PY="${PY:-$(command -v python3 || command -v python)}"
# Windows 上 Python 默认按 cp1252 编码 stdout，脚本里的中文会 UnicodeEncodeError
export PYTHONUTF8="${PYTHONUTF8:-1}"
export PYTHONIOENCODING="${PYTHONIOENCODING:-utf-8}"

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

# 关卡名 → .adofai 路径（level 在这里、也只在这里解压）
prepare_level() {
    case "$1" in
        tempest) printf '%s' "$EX/assets/Tempest.adofai" ;;
        level)
            # 压缩包原样提交，只在这里解压（LEVEL_ZIP 可指向别的 zip，便于本地试）
            mkdir -p "$BUILD/levels"
            "$PY" -c "import zipfile,sys; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" \
                  "${LEVEL_ZIP:-$ROOT/levels/level.zip}" "$BUILD/levels"
            printf '%s' "$BUILD/levels/level.adofai" ;;
        *) printf '%s' "$1" ;;
    esac
}

# 与 ADOCAO 的 hitsoundKey() 一一对应：把同一个样本铺满所有类型名，
# 于是无论谱面写的是哪种 hitsound，两侧用的都是同一份 hit.wav。
HIT_TYPES="Kick KickHouse KickChroma KickRupture SnareAcoustic2 SnareHouse SnareVapor
           ClapHit ClapHitEcho Hat HatHouse Chuck Hammer Shaker ShakerLoud Sidestick Stick
           ReverbClack ReverbClap Squareshot FireTile IceTile PowerUp PowerDown
           VehiclePositive VehicleNegative Sizzle"

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
    cc --version 2>/dev/null | head -1 || true
    command -v cl >/dev/null 2>&1 && cl 2>&1 | head -1 || true
} | tee "$OUT/env.txt"

step "③ 配置 / 构建（两侧同为 Release、O2，不开 -march=native）"
GEN=""
command -v ninja >/dev/null 2>&1 && GEN="-G Ninja"
cmake -S "$ROOT" -B "$BUILD" -DCMAKE_BUILD_TYPE=Release $GEN
cmake --build "$BUILD" --parallel

ADOCAO_EXE="$(exe adocao_gen)"
REF_EXE="$(exe ref_gen)"
HIT_WAV="$EX/assets/hit.wav"

for name in ${LEVELS//,/ }; do
    LEVEL="$(prepare_level "$name")"
    [ -f "$LEVEL" ] || { echo "❌ 关卡不存在: $LEVEL" >&2; exit 1; }

    mkdir -p "$OUT/$name/assets"
    cp "$HIT_WAV" "$OUT/$name/assets/hit.wav"
    for t in $HIT_TYPES; do cp "$HIT_WAV" "$OUT/$name/assets/$t.wav"; done

    step "④ 关卡 $name：$(du -h "$LEVEL" 2>/dev/null | cut -f1) $LEVEL"
    for i in $(seq 1 "$RUNS"); do
        printf '\n── %s 第 %d/%d 次：ADOCO ──\n' "$name" "$i" "$RUNS"
        ( cd "$OUT/$name" && "$ADOCAO_EXE" "$LEVEL" "$OUT/$name/assets" \
            "$OUT/$name/adocao.run$i.wav" "$OUT/$name/metrics_adocao.run$i.txt" \
            "$OUT/$name/timeline_adocao.run$i.f64" Kick ) 2>&1 | tee "$OUT/$name/log_adocao.run$i.txt"

        printf '\n── %s 第 %d/%d 次：ADOFAI_HitSound ──\n' "$name" "$i" "$RUNS"
        ( cd "$OUT/$name" && "$REF_EXE" "$LEVEL" "$HIT_WAV" \
            "$OUT/$name/ref.run$i.wav" "$OUT/$name/metrics_ref.run$i.txt" \
            "$OUT/$name/timeline_ref.run$i.f64" ) 2>&1 | tee "$OUT/$name/log_ref.run$i.txt"

        # 巨型关卡的时间轴 dump 可达数百 MB，立刻压掉（analyze.py 能直接读 .f64.gz）
        gzip -f "$OUT/$name"/timeline_*."run$i".f64
    done

    step "⑤ 关卡 $name：分析（挑最快一次 → 对齐时间轴 → 响度/音频指标 → 图表 / A-B 片段）"
    "$PY" "$ROOT/tools/analyze.py" --out "$OUT/$name" --label "${LABEL:-$(uname -s -m)}" \
        --level-name "$name"
done

step "⑥ 跨关卡汇总"
"$PY" "$ROOT/tools/analyze.py" --summary "$OUT"
