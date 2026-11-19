#!/usr/bin/env python3
"""检查 Android Kotlin 文件的 package 声明是否残留上游包名。

背景
----
本 fork 将 Android 包名从 ``com.carriez.flutter_hbb`` 改为 ``com.rustdesk.app``，
源码目录也随之重命名。上游新增的 Kotlin 文件（如 v1.5.1 的 ``Document*.kt``）
在合并后会落到 ``com/rustdesk/app/`` 目录下，但文件内的 ``package`` 声明仍是
旧包名，导致 Kotlin 报 ``Unresolved reference`` —— 而这个错误要等 Rust 交叉编译
（约 40 分钟）之后才会在 gradle 阶段暴露。

在编译前跑一遍本脚本，可在 1 分钟内发现问题，避免浪费整轮编译。

用法
----
    python3 .github/scripts/check_android_package.py [项目根目录]

退出码：0 = 通过；1 = 发现残留包名。

注意
----
只匹配 ``package`` 声明里的旧包名，不要求 package 与目录一致：
上游存在 ``package hbb`` 这类历史遗留（Kotlin 不强制 package 匹配目录），
它们能正常编译，不应被当错误处理。

第二类检查：Rust 侧的 JNI 导出符号。Kotlin 的 ``external fun`` 由 JVM 按
``Java_<包名>_<类名>_<方法名>`` 查找，包名改了而 ``#[no_mangle]`` 符号没改时，
编译期没有任何提示，只在运行时抛 ``UnsatisfiedLinkError`` 直接闪退
（v1.5.3 的 ``DocumentLogs.setEnabled`` 就是这样崩的）。
"""

from __future__ import annotations

import os
import re
import sys

# 本 fork 使用的当前包名
CURRENT_PACKAGE = "com.rustdesk.app"
# 上游原始包名的特征片段，命中即为漏改
LEGACY_MARKERS = ("carriez", "flutter_hbb")

# 相对项目根目录的 Android 源码路径
ANDROID_ROOT = os.path.join("flutter", "android")

# 匹配行首的 package 声明（允许多余空白）
PACKAGE_RE = re.compile(r"(?m)^[ \t]*package[ \t]+([\w.]+)")

# Rust 源码目录（JNI 导出符号可能出现在这里）
RUST_ROOTS = ("src", "libs")

# 匹配 `fn Java_xxx`（JNI 导出符号；`_1` 是 JVM 对 `_` 的编码）
JNI_RE = re.compile(r"(?m)^\s*(?:pub\s+)?(?:unsafe\s+)?extern\s+\"system\"\s+fn\s+(Java_\w+)")


def scan(root: str) -> tuple[int, list[tuple[str, str, int]]]:
    """扫描 Android 目录下所有 .kt 文件。

    :param root: 项目根目录
    :return: (扫描的 .kt 文件数, 问题列表)，问题列表元素为
             (文件相对路径, package 声明原文, 行号)
    """
    base = os.path.join(root, ANDROID_ROOT)
    if not os.path.isdir(base):
        return 0, []

    total = 0
    problems: list[tuple[str, str, int]] = []

    for dirpath, _dirnames, filenames in os.walk(base):
        for name in filenames:
            if not name.endswith(".kt"):
                continue
            full = os.path.join(dirpath, name)
            total += 1
            with open(full, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
            for match in PACKAGE_RE.finditer(text):
                pkg = match.group(1)
                if any(marker in pkg for marker in LEGACY_MARKERS):
                    line = text.count("\n", 0, match.start()) + 1
                    problems.append(
                        (os.path.relpath(full, root), match.group(0).strip(), line)
                    )

    return total, problems


def scan_jni(root: str) -> list[tuple[str, str, int]]:
    """扫描 Rust 侧的 JNI 导出符号，找出仍带上游包名的。

    :param root: 项目根目录
    :return: [(文件相对路径, 符号名, 行号)]
    """
    problems: list[tuple[str, str, int]] = []
    for sub in RUST_ROOTS:
        base = os.path.join(root, sub)
        if not os.path.isdir(base):
            continue
        for dirpath, _dirnames, filenames in os.walk(base):
            for name in filenames:
                if not name.endswith(".rs"):
                    continue
                full = os.path.join(dirpath, name)
                with open(full, encoding="utf-8", errors="replace") as fh:
                    text = fh.read()
                for match in JNI_RE.finditer(text):
                    symbol = match.group(1)
                    # `_1` 是 JVM 对 `_` 的编码，flutter_hbb 会变成 flutter_1hbb
                    if "carriez" in symbol or "flutter_1hbb" in symbol:
                        line = text.count("\n", 0, match.start()) + 1
                        problems.append((os.path.relpath(full, root), symbol, line))
    return problems


def main(argv: list[str]) -> int:
    root = argv[1] if len(argv) > 1 else os.getcwd()
    total, problems = scan(root)
    jni_problems = scan_jni(root)

    print(f"scanned {total} kotlin file(s) under {ANDROID_ROOT}")

    for path, decl, line in problems:
        print(
            f"::error file={path},line={line}::{decl} "
            f"—— 包名未随 fork 改写为 {CURRENT_PACKAGE}"
        )

    for path, symbol, line in jni_problems:
        print(
            f"::error file={path},line={line}::{symbol} "
            f"—— JNI 符号仍是上游包名，运行时将抛 UnsatisfiedLinkError（应改为 "
            f"Java_{CURRENT_PACKAGE.replace('.', '_')}_...）"
        )

    if problems or jni_problems:
        print(
            f"\n❌ 发现 {len(problems)} 处残留 Kotlin 包名、"
            f"{len(jni_problems)} 处残留 JNI 符号，请修正后重跑"
        )
        return 1

    print(f"✅ Android 包名检查通过（当前包名 {CURRENT_PACKAGE}）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
