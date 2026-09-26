#!/usr/bin/env python3
"""ADOCAO 剥离件的最小可编译性补丁。

只做一件事：给 LevelData.hpp 补上它用到却没写的标准头 <array>。
上游能编过是因为 GCC/同一 TU 里其它头顺带引入了它；换编译器（MSVC）就会挂。
这是「补一个标准头」，不是改逻辑——补丁内容固定在下面，跑完会打印实际改动数。

用法: patch_adocao.py <剥离出的 adocao 目录>
"""
import pathlib
import sys

FIXES = [
    # (相对路径, 需要存在的用法, 缺哪个标准头就补哪个)
    ("core/level/LevelData.hpp", "std::array", "#include <array>"),
]


def main() -> None:
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    root = pathlib.Path(sys.argv[1])
    changed = 0
    for rel, used, header in FIXES:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        if used not in text or header in text:
            continue
        marker = "#pragma once\n"
        text = text.replace(marker, marker + f"\n{header}   // 由 patch_adocao.py 补（上游靠传递包含）\n", 1)
        path.write_text(text, encoding="utf-8")
        changed += 1
        print(f"[patch_adocao] {rel}: += {header}（因为用到 {used}）")
    print(f"[patch_adocao] 完成，改动 {changed} 个文件，共 {len(FIXES)} 条规则")


if __name__ == "__main__":
    main()
