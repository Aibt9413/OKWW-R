#!/usr/bin/env python3
"""
把 launcher exe + 整个程序目录打包成单个自解压 exe（SFX）。

归档格式（与 launcher/src/archive.rs 严格对应）：
    [launcher exe 原样]
    [数据区: 各文件内容按条目顺序拼接]
    [条目表: 每条 = name_len(u32) + off(u64) + len(u32) + name bytes]
    [footer: magic[8] + data_len(u64) + entry_cnt(u32) + data_sha[32]
                     + table_off(u64) + reserved(u32)]  = 64B

安全/版权要点：
  - 数据区 SHA256 同时写入 footer 与固化进 main.rs 常量（双保险，改 footer 无用）。
  - 只打包二进制/数据，不打包任何 .py 源码明文（调用方传 standalone dist 目录）。
  - 加密模型 .dat 以「加密状态」入包，运行时内存解密，不产生明文。

用法:
    python tools/pack_single.py --dist build/main.dist --launcher launcher/dist/wwcore.exe \
                               --out build/wwcore.exe [--inject-hash]
    python tools/pack_single.py --verify build/wwcore.exe     # 校验已打包单文件
"""

from __future__ import annotations

import argparse
import hashlib
import io
import os
import re
import struct
import sys

MAGIC = b"WWPKG01\n"
FOOTER_SIZE = 64
MAIN_RS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "launcher", "src", "main.rs")
HASH_PATTERN = r'(const EXPECTED_ARCHIVE_SHA256: &str = ")[^"]*(";)'


def collect_files(dist):
    """返回 [(相对路径(posix), 绝对路径)]，按路径排序保证确定性。"""
    out = []
    for dirpath, dirnames, filenames in os.walk(dist):
        dirnames.sort()
        for fn in sorted(filenames):
            full = os.path.join(dirpath, fn)
            rel = os.path.relpath(full, dist).replace("\\", "/")
            out.append((rel, full))
    out.sort(key=lambda x: x[0])
    return out


def build_archive(dist):
    """构造 (数据区, 条目表, 数据区sha256, 条目数)。"""
    files = collect_files(dist)
    data = bytearray()
    entries = []  # (name_len, off, len, name_bytes)
    for rel, full in files:
        blob = open(full, "rb").read()
        off = len(data)
        data.extend(blob)
        name_b = rel.encode("utf-8")
        entries.append((len(name_b), off, len(blob), name_b))

    table = bytearray()
    for name_len, off, length, name_b in entries:
        # name_len(u32) + off(u64) + len(u32) —— 与 Rust 侧 16B 头一致
        table.extend(struct.pack("<IQI", name_len, off, length))
        table.extend(name_b)

    sha = hashlib.sha256(bytes(data)).hexdigest()
    return bytes(data), bytes(table), sha, len(entries)


def pack(dist, launcher, out, inject_hash):
    if not os.path.isdir(dist):
        raise SystemExit("dist 目录不存在: " + dist)
    if not os.path.isfile(launcher):
        raise SystemExit("launcher 不存在: " + launcher)

    launcher_bytes = open(launcher, "rb").read()
    data, table, sha, count = build_archive(dist)
    table_off = len(launcher_bytes) + len(data)

    # footer: magic8 + data_len8 + cnt4 + sha32 + table_off8 + reserved4 = 64B
    footer = bytearray()
    footer.extend(MAGIC)
    footer.extend(struct.pack("<Q", len(data)))
    footer.extend(struct.pack("<I", count))
    footer.extend(bytes.fromhex(sha))
    footer.extend(struct.pack("<Q", table_off))
    footer.extend(struct.pack("<I", 0))  # reserved
    assert len(footer) == FOOTER_SIZE, len(footer)

    result = launcher_bytes + data + table + bytes(footer)
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with open(out, "wb") as f:
        f.write(result)

    print("packed: %s" % out)
    print("  launcher : %d B" % len(launcher_bytes))
    print("  data     : %d B (%d entries)" % (len(data), count))
    print("  sha256   : %s" % sha)
    print("  total    : %.1f MB" % (len(result) / 1024 / 1024))

    if inject_hash:
        src = io.open(MAIN_RS, "r", encoding="utf-8").read()
        if not re.search(HASH_PATTERN, src):
            raise SystemExit("main.rs 找不到 EXPECTED_ARCHIVE_SHA256 常量")
        new = re.sub(HASH_PATTERN, lambda m: m.group(1) + sha + m.group(2), src, count=1)
        io.open(MAIN_RS, "w", encoding="utf-8", newline="").write(new)
        print("  hash injected into main.rs")


def verify(path):
    raw = open(path, "rb").read()
    if len(raw) < FOOTER_SIZE:
        raise SystemExit("文件过小，不是 SFX 归档")
    footer = raw[-FOOTER_SIZE:]
    if footer[:8] != MAGIC:
        raise SystemExit("尾部无 SFX magic，不是单文件归档（或已损坏）")
    data_len = struct.unpack_from("<Q", footer, 8)[0]
    count = struct.unpack_from("<I", footer, 16)[0]
    sha = footer[20:52].hex()
    table_off = struct.unpack_from("<Q", footer, 52)[0]
    data_off = table_off - data_len
    actual = hashlib.sha256(raw[data_off:data_off + data_len]).hexdigest()

    # 逐条解析条目表，确认路径安全、偏移不越界
    pos = table_off
    bad_paths = []
    max_off = 0
    for _ in range(count):
        name_len, off, length = struct.unpack_from("<IQI", raw, pos)
        pos += 16
        name = raw[pos:pos + name_len].decode("utf-8", "replace")
        pos += name_len
        if name.startswith("/") or name.startswith("\\") or ".." in name.split("/") or re.match(r"^[A-Za-z]:", name):
            bad_paths.append(name)
        max_off = max(max_off, off + length)
    ok = (actual == sha) and not bad_paths and max_off <= data_len and pos <= len(raw) - FOOTER_SIZE
    print("verify %s" % path)
    print("  entries   : %d" % count)
    print("  data_len  : %d" % data_len)
    print("  sha256    : %s" % sha)
    print("  actual    : %s" % actual)
    print("  bad paths : %s" % (bad_paths or "none"))
    print("  RESULT    : %s" % ("OK" if ok else "FAIL"))
    return 0 if ok else 1


def main():
    ap = argparse.ArgumentParser(description="SFX 单文件打包工具")
    ap.add_argument("--dist", help="程序目录（nuitka standalone dist）")
    ap.add_argument("--launcher", help="Rust launcher exe")
    ap.add_argument("--out", help="输出单 exe 路径")
    ap.add_argument("--inject-hash", action="store_true", help="把数据区哈希固化进 main.rs")
    ap.add_argument("--verify", metavar="EXE", help="校验已打包单文件")
    args = ap.parse_args()

    if args.verify:
        return verify(args.verify)
    if not (args.dist and args.launcher and args.out):
        ap.error("打包需要 --dist --launcher --out")
    pack(args.dist, args.launcher, args.out, args.inject_hash)
    return 0


if __name__ == "__main__":
    sys.exit(main())
