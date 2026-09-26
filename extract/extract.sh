#!/usr/bin/env bash
# 剥离：把两个项目的「打击音生成」相关源码取出来，落到 build/extracted/。
#
# 只负责取源 + 调用改写脚本，不参与构建。上游一更新，重跑本脚本即可，
# 因此仓库里不需要保存任何代码副本（不会出现漂移）。
#
# 用法：
#   extract/extract.sh                                  # 从 GitHub 浅克隆（CI 用）
#   ADOCAO_SRC=/path HITSOUND_SRC=/path extract/extract.sh   # 用本地副本（开发用）
#   ADOCAO_REF=<sha|branch> HITSOUND_REF=<sha|branch> …      # 钉住版本
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/build/extracted"
CACHE="$ROOT/build/upstream"
ADOCAO_REPO="${ADOCAO_REPO:-https://github.com/Pitaki-Dev/ADOCAO.git}"
HITSOUND_REPO="${HITSOUND_REPO:-https://github.com/Maicy0609/ADOFAI_HitSound.git}"

# ── 取源：本地路径优先，否则浅克隆（支持分支/标签/SHA）──
resolve() { # $1=本地路径 $2=repo $3=落地目录 $4=ref
    local local_path="$1" repo="$2" dest="$3" ref="$4"
    if [ -n "$local_path" ] && [ -d "$local_path" ]; then
        printf '%s' "$(cd "$local_path" && pwd)"; return
    fi
    rm -rf "$dest"
    if [ -z "$ref" ]; then
        git clone --depth 1 -q "$repo" "$dest"
    elif git clone --depth 1 -q --branch "$ref" "$repo" "$dest" 2>/dev/null; then
        :
    else
        git clone -q "$repo" "$dest" && git -C "$dest" checkout -q "$ref"
    fi
    printf '%s' "$dest"
}

ADOCAO_SRC_DIR="$(resolve "${ADOCAO_SRC:-}" "$ADOCAO_REPO" "$CACHE/adocao" "${ADOCAO_REF:-}")"
HS_SRC_DIR="$(resolve "${HITSOUND_SRC:-}" "$HITSOUND_REPO" "$CACHE/adofai_hitsound" "${HITSOUND_REF:-}")"

rm -rf "$OUT"
mkdir -p "$OUT/adocao" "$OUT/shims" "$OUT/ref" "$OUT/assets"

# ── ADOCAO：只带「解析 + 时间轴 + 合成」这条链，逐字复制 ──
ADOCAO_FILES=(
    core/level/LevelData.hpp            core/level/LevelData.cpp
    core/level/JsonCleaner.hpp          core/level/JsonCleaner.cpp
    core/timeline/Timeline.hpp          core/timeline/Timeline.cpp
    core/timeline/HitsoundTimestampGroup.hpp
    core/util/Logger.hpp                core/util/Logger.cpp
    core/util/DataFile.hpp              core/util/DataFile.cpp
    audio/HitsoundManager.hpp           audio/HitsoundManager.cpp
)
for f in "${ADOCAO_FILES[@]}"; do
    mkdir -p "$OUT/adocao/$(dirname "$f")"
    cp "$ADOCAO_SRC_DIR/$f" "$OUT/adocao/$f"
done
cp "$ROOT/extract/shims/AudioEngine.hpp" "$OUT/shims/AudioEngine.hpp"
python3 "$ROOT/extract/patch_adocao.py" "$OUT/adocao"

# ── ADOFAI_HitSound：HitSound.cpp → hitsound_core.{hpp,cpp} ──
python3 "$ROOT/extract/port_ref.py" "$HS_SRC_DIR/HitSound.cpp" "$OUT/ref"

# ── 素材：两侧都必须用同一个打击音样本（ADOFAI_HitSound 的 hit.wav）──
# ADOCAO 按谱面的 hitsound 类型取 "<类型>.wav"，Tempest 的类型是 Kick，
# 所以同一份样本要同时以 hit.wav（ref 侧）和 Kick.wav（adocao 侧）出现。
cp "$HS_SRC_DIR/x64/Release/Tempest.adofai" "$OUT/assets/Tempest.adofai"
cp "$HS_SRC_DIR/x64/Release/hit.wav"        "$OUT/assets/hit.wav"
cp "$OUT/assets/hit.wav"                    "$OUT/assets/Kick.wav"

# ── 溯源：报告里要能说清「这一版结果对应上游哪个提交」──
{
    echo "extracted_at   $(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "adocao_repo    $ADOCAO_REPO"
    echo "adocao_source  $ADOCAO_SRC_DIR"
    echo "adocao_commit  $(git -C "$ADOCAO_SRC_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "adocao_dirty   $(git -C "$ADOCAO_SRC_DIR" status --porcelain 2>/dev/null | wc -l | tr -d ' ')"
    echo "hitsound_repo  $HITSOUND_REPO"
    echo "hitsound_path  $HS_SRC_DIR/HitSound.cpp"
    echo "hitsound_commit $(git -C "$HS_SRC_DIR" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "hit_wav        $(cd "$(dirname "$OUT/assets/hit.wav")" && pwd)/hit.wav"
} | tee "$OUT/PROVENANCE.txt"
