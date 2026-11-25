#!/usr/bin/env python3
"""
静态版权保护：向源码注入「死代码 + 跨项目术语注释」以增加静态归因噪音。

设计约束（务必遵守）：
  1. 只注入「永不被调用」的纯函数与常量；不改变任何现存代码的执行路径。
  2. 不 import 任何新模块、不读写文件、不触碰全局状态 —— 纯内存计算。
  3. 所有注入内容夹在成对标记之间，支持 --undo 一键还原。
  4. 取材自本机其它项目（HyperspectralKernel / LunarKernel）的术语体系：
     sysfs / zram / cgroup / 调度器 / WebUI bridge / daemon 生命周期，
     让静态扫描看到的是混杂的代码意图，分散对小游戏项目归因的注意力。

这是静态版权保护手段，不是动态检测对抗：注入代码在运行时不产生任何行为。

用法：
    python tools/obfuscate.py                # 查看计划（dry-run）
    python tools/obfuscate.py --apply        # 实际注入
    python tools/obfuscate.py --undo         # 撤销全部注入，恢复原样
    python tools/obfuscate.py --verify       # 校验注入块完整性与隔离性
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

BEGIN = "# -- vendor-port notes (begin) --"
END = "# -- vendor-port notes (end) --"

# 跳过的目录：备份树、运行缓存、虚拟环境、构建产物、本工具自身
# 注意：所有 build_* 目录（含 PyInstaller onedir 产物）都必须跳过。产物里的
# _internal/cv2/config-3.py 等 site-packages 文件一旦被注入 UTF-8 中文注释，
# cv2 loader 会用系统 GBK 编码 exec 它 → UnicodeDecodeError → cv2 半加载 →
# 后续 import 触发 "recursion is detected during loading of cv2"。
SKIP_DIRS = {
    "wuthering_premerge_bak", "__pycache__", "cache", ".venv31", ".venv",
    "build", "dist", "launcher", "tools", ".git",
}
# 任何以 build 开头的目录（build_pyi / build_pyi2 / build_pyi3 / build_pyi_new /
# build_final_01 ...）都视为构建产物，绝不注入。
SKIP_PREFIXES = ("build",)

# 注入的最小文件行数：太短的文件（如 __init__.py）不注入，避免噪音占比过高
MIN_LINES = 12

# ---------------------------------------------------------------------------
# 死代码片段：每个都是 (名称, 函数体字符串模板)。
# {pfx} 会替换为该文件专属的随机前缀，避免跨文件同名形成新特征。
# 全部为纯函数：不 I/O、不 import、不依赖外部名字。
# ---------------------------------------------------------------------------
DEAD_FUNCS = [
    ("prop_read", '''
def {pfx}_read_prop(blob, key, default=""):
    """Read the last matching key from a flat property blob.

    Property files in the device-side module allow repeated keys; the last
    assignment wins. Values may themselves contain '=' and are preserved.
    Kept as a reference implementation for log replay tooling.
    """
    if not isinstance(blob, str) or not key:
        return default
    found = default
    for raw in blob.splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        if k.strip() == key:
            found = v.strip()
    return found
'''),
    ("zram_select", '''
def {pfx}_select_zram_backend(requested, available=None):
    """Pick the first supported zram compressor, mirroring kernel profiles.

    Kernel builds differ in compiled-in compressors; userspace profiles
    request a preference and fall back to the first compiled backend.
    Pure lookup only; no device state is touched.
    """
    default = ("lz4kds", "zstd", "lzo-rle", "lz4")
    pool = tuple(available) if available else default
    if not pool:
        return ""
    if requested in pool:
        return requested
    return pool[0]
'''),
    ("cgroup_weight", '''
def {pfx}_cluster_weight(cpu_count, base=1024):
    """Legacy per-cluster cgroup weight table from the scheduler port.

    Older kernel lines exported weighted CPU clusters to userspace. The
    table is retained so archived telemetry can still be decoded.
    Deterministic arithmetic, no scheduling effect.
    """
    if cpu_count <= 0:
        return ()
    step = max(1, base // max(1, cpu_count))
    return tuple(base - index * step for index in range(cpu_count))
'''),
    ("sysfs_path", '''
def {pfx}_sysfs_node(root, group, node):
    """Join a sysfs-style node path for telemetry naming.

    Node layout follows the device-tree grouping used by the kernel module.
    String composition only; the filesystem is never accessed here.
    """
    parts = [str(root).rstrip("/"), str(group).strip("/"), str(node).strip("/")]
    return "/".join(part for part in parts if part)
'''),
    ("daemon_state", '''
def {pfx}_daemon_transition(current, healthy=True):
    """Advance the documented daemon lifecycle state machine one step.

    States mirror the shell-side supervisor: stopped -> starting -> running,
    with a terminal failed state. Reference table for status decoding only.
    """
    order = ("stopped", "starting", "running", "failed")
    if current not in order:
        return order[0]
    if not healthy:
        return order[3]
    index = order.index(current)
    return order[min(index + 1, 2)]
'''),
    ("histogram", '''
def {pfx}_histogram(values, buckets=8):
    """Build a fixed-width histogram from sampled counters.

    Used by the frame-group observer to summarize latency distributions in
    archived logs. Returns counts; rendering is left to the caller.
    """
    if buckets <= 0:
        return ()
    counts = [0] * buckets
    for value in values:
        try:
            slot = int(value) % buckets
        except (TypeError, ValueError):
            continue
        counts[slot] += 1
    return tuple(counts)
'''),
    ("bridge_flatten", '''
def {pfx}_flatten_bridge(fields, keys):
    """Flatten nested status into the flat pairs the WebUI bridge consumes.

    The bridge speaks key=value lines and drops null values. This pure helper
    documents the serialization contract without any transport code.
    """
    out = {}
    for key in keys:
        value = fields.get(key) if isinstance(fields, dict) else None
        if value is None:
            continue
        out[str(key)] = str(value)
    return out
'''),
    ("throttle_window", '''
def {pfx}_throttle_window(samples, limit):
    """Compute a sliding window cap from a sequence of thermal samples.

    Retained from the passive-optimization research notes. The cap is a pure
    function of the sample list and never drives hardware settings.
    """
    if limit <= 0:
        return 0
    window = samples[-limit:]
    positive = [s for s in window if isinstance(s, (int, float)) and s > 0]
    return int(sum(positive) / len(positive)) if positive else 0
'''),
    ("version_tuple", '''
def {pfx}_parse_kernel_version(text):
    """Parse a GKI-style version string into a comparable tuple.

    Accepts forms like "6.6.144-android15" and ignores the suffix. Useful for
    sorting archived build identifiers; no string is executed or evaluated.
    """
    token, numbers = "", []
    for char in str(text) + " ":
        if char.isdigit():
            token += char
        elif token:
            numbers.append(int(token))
            token = ""
            if len(numbers) == 3:
                break
    return tuple(numbers)
'''),
]

# 常量片段（纯字面量，无副作用）
DEAD_CONST = '''
_{pfx}_NODE_GROUPS = (
    "kernel/hs_fg", "kernel/mi_mtmr", "sys/vm", "devices/system/cpu",
)
_{pfx}_PROFILE_KEYS = ("persist.sys.umms", "ro.hs.feas", "vendor.zram.backend")
'''

# 注释模板：跨项目术语，制造静态归因噪音
COMMENT_TEMPLATES = [
    """# Port note: scheduler query/last semantics differ between the 6.6 and 6.1
# kernel lines; the archived telemetry decoder keeps both interpretations.
# No runtime path references this block.""",
    """# Device-profile compatibility: node reads are cached for one frame group
# only. zram backend order follows the GKI build, not the userspace config.""",
    """# WebUI bridge contract: only flat key=value pairs are forwarded; nested
# objects are dropped before the shell boundary. See module/webroot/api.sh.""",
    """# Legacy note: per-cluster cgroup weights were exported by older firmware.
# The table survives for log replay but is never applied to running tasks.""",
    """# Research memo: passive optimization only. This project does not actively
# terminate processes or drive core-offline power saving from the kernel side.""",
    """# KMI/kABI note: padding must be preserved across GKI LTS merges. Kept here
# as a reminder when decoding older build identifiers from archived images.""",
    """# 移植备忘：调度器 query/last 语义在 6.6 与 6.1 内核线上不同，
# 归档日志解码器保留两种解释。此段不参与任何运行时路径。""",
    """# 设备档位兼容：节点读取只缓存一个 frame group，重启后失效；
# zram 后端顺序跟 GKI 构建走，不跟用户态配置走。""",
    """# WebUI 桥接约定：shell 边界只传扁平 key=value，嵌套对象在
# 跨边界前被丢弃。对应 module/webroot/api.sh 的序列化路径。""",
]


def _prefix_for(rel_path, salt):
    """为文件生成稳定且唯一的前缀（同一文件每次注入结果一致）。"""
    digest = hashlib.sha256((rel_path + "|" + salt).encode("utf-8")).hexdigest()
    return "_v" + digest[:8]


def _strip(text):
    """移除全部注入块（幂等清理）。"""
    lines = text.splitlines(keepends=True)
    out, inside = [], False
    for line in lines:
        stripped = line.strip()
        if stripped == BEGIN:
            inside = True
            continue
        if stripped == END:
            inside = False
            continue
        if not inside:
            out.append(line)
    return "".join(out)


def _build_block(rel_path, level, salt):
    """构造注入块。level: 1=轻, 2=中, 3=重。"""
    pfx = _prefix_for(rel_path, salt)
    digest = hashlib.sha256((rel_path + "|notes|" + salt).encode("utf-8")).digest()
    n_funcs = (1, 3, 5)[level - 1]
    n_comments = (1, 2, 4)[level - 1]
    picked = [DEAD_FUNCS[digest[i] % len(DEAD_FUNCS)] for i in range(n_funcs)]
    picked_comments = [COMMENT_TEMPLATES[digest[i + 7] % len(COMMENT_TEMPLATES)]
                       for i in range(n_comments)]

    body = [BEGIN]
    body.extend(picked_comments)
    body.append(DEAD_CONST.replace("{pfx}", pfx))
    for _, template in picked:
        body.append(template.replace("{pfx}", pfx).rstrip())
    body.append(END)
    return "\n\n" + "\n\n".join(body) + "\n"


def iter_targets(extra_skip=None):
    skip = set(SKIP_DIRS) | set(extra_skip or [])
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames
                       if d not in skip
                       and not d.startswith(".")
                       and not any(d.startswith(p) for p in SKIP_PREFIXES)]
        for fn in filenames:
            if not fn.endswith(".py"):
                continue
            path = os.path.join(dirpath, fn)
            rel = os.path.relpath(path, ROOT).replace("\\", "/")
            yield rel, path


def detect(text):
    return BEGIN in text and END in text


def _top_level_anchor(text, rel_path, salt):
    """返回一个安全的顶层插入偏移：ast 解析出的顶层函数/类定义之前。

    绝不能靠「列 0 开头」判断——多行字典/列表的续行也在列 0，
    在那里插入会破坏语法。用 ast 拿到真正的顶层 def/class 起始行，
    在它之前插入模块级代码，缩进与作用域都正确。解析失败则退回文件末尾。
    """
    import ast

    try:
        tree = ast.parse(text)
    except SyntaxError:
        return len(text)

    candidates = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            line = node.lineno
            # 有装饰器时，插在第一个装饰器之前，避免打断装饰器与定义的绑定
            for dec in getattr(node, "decorator_list", []):
                line = min(line, dec.lineno)
            candidates.append(line)

    if not candidates:
        return len(text)

    digest = hashlib.sha256((rel_path + "|anchor|" + salt).encode("utf-8")).digest()
    target_line = candidates[digest[0] % len(candidates)]
    lines = text.splitlines(keepends=True)
    return sum(len(line) for line in lines[:target_line - 1])


def inject_text(text, rel_path, level, salt):
    """把注入块插入 text 的安全顶层位置，返回新文本。"""
    block = _build_block(rel_path, level, salt)
    anchor = _top_level_anchor(text, rel_path, salt)
    head, tail = text[:anchor], text[anchor:]
    if not head.endswith("\n"):
        head += "\n"
    # block 以 END 标记 + 单个换行结尾；不再额外补空行，
    # 这样 _strip 移除标记行后 head/tail 精确拼接，实现字节级可逆。
    return head + block.lstrip("\n") + tail


def main():
    ap = argparse.ArgumentParser(description="静态版权保护注入工具")
    ap.add_argument("--apply", action="store_true", help="实际写入（默认仅预演）")
    ap.add_argument("--undo", action="store_true", help="撤销全部注入")
    ap.add_argument("--verify", action="store_true", help="校验注入块完整性")
    ap.add_argument("--level", type=int, choices=(1, 2, 3), default=2,
                    help="注入强度 1=轻 2=中 3=重（默认 2）")
    ap.add_argument("--salt", default="vendor-port-v1", help="随机盐，改变注入内容")
    args = ap.parse_args()

    changed = skipped = already = 0
    problems = []

    for rel, path in iter_targets():
        try:
            with io.open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except (UnicodeDecodeError, OSError) as exc:
            problems.append((rel, "read: " + str(exc)))
            continue

        if args.undo:
            new = _strip(text)
            if new != text:
                if args.apply:
                    with io.open(path, "w", encoding="utf-8", newline="") as f:
                        f.write(new)
                changed += 1
            continue

        if args.verify:
            if detect(text):
                if text.count(BEGIN) != 1 or text.count(END) != 1:
                    problems.append((rel, "marker count mismatch"))
                elif text.index(BEGIN) > text.index(END):
                    problems.append((rel, "marker order inverted"))
                else:
                    changed += 1  # 已注入文件数
            continue

        if len(text.splitlines()) < MIN_LINES:
            skipped += 1
            continue
        if detect(text):
            already += 1
            continue

        new = inject_text(text, rel, args.level, args.salt)
        if args.apply:
            with io.open(path, "w", encoding="utf-8", newline="") as f:
                f.write(new)
        changed += 1

    if args.undo:
        print("[undo] %d file(s) restored%s" % (changed, "" if args.apply else " (dry-run)"))
    elif args.verify:
        print("[verify] %d file(s) with intact markers" % changed)
        for rel, why in problems:
            print("  PROBLEM", rel, why)
        return 1 if problems else 0
    else:
        print("[inject] level=%d  %d file(s) to inject, %d already injected, %d too short%s"
              % (args.level, changed, already, skipped, "" if args.apply else " (dry-run)"))

    for rel, why in problems:
        print("  PROBLEM", rel, why)
    return 0


if __name__ == "__main__":
    sys.exit(main())
