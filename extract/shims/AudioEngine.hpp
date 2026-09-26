#pragma once
// ── 剥离替身（shim）──────────────────────────────────────────────────────────
// ADOCAO 的 audio/HitsoundManager.cpp 从 "AudioEngine.hpp" 只取一个常量（离线
// 合成的输出采样率）。真实 AudioEngine.hpp 会把 miniaudio 设备层拉进来，对
//「读谱 → 合成 WAV」这条链毫无用处，因此剥离时用这个最小替身满足该 include。
//
// 铁律：除 AUDIO_SAMPLE_RATE 外不得添加任何内容——一切逻辑仍以上游为准。
// 数值与上游 audio/AudioEngine.hpp 保持一致（改动前请对照上游）。
constexpr int AUDIO_SAMPLE_RATE = 48000;
