"""模型保险库：把 .onnx 加密成 .dat，运行时在内存解密，硬盘不落明文。

用途是**版权保护**（防止自己训练的模型被直接拷走），不是对抗扫描，
所以设计目标是"拷走也用不了"，而不是"藏起来"。

加密方式
--------
Windows DPAPI（``CryptProtectData``），纯 ctypes，无第三方依赖：

  - 默认 **用户作用域**：密文只在「当前用户 + 当前机器」上能解开。
    拷到别的电脑、重装系统后都解不开 —— 这正是防拷贝要的效果。
  - 不需要在代码里保存任何密钥（钥匙由系统按用户凭据派生）。

容器格式
--------
::

    MAGIC       7 字节   b"SCMOD1\\n"   （原注释误写 8 字节；代码用 len(MAGIC)，故 Python 侧无影响）
    HEADER_LEN  4 字节   little-endian uint32
    HEADER      HEADER_LEN 字节 UTF-8 JSON：{"algo","size","sha256"}
    PAYLOAD     剩余字节  DPAPI 密文

命令行
------
::

    python -m okunified.security.model_vault encrypt <src.onnx> <dst.dat>
    python -m okunified.security.model_vault verify  <file.dat>
"""
import ctypes
import hashlib
import json
import os
import struct
import sys
from ctypes import wintypes

MAGIC = b"SCMOD1\n"
HEADER_LEN_FMT = "<I"
ALGO_DPAPI = "dpapi-user"

_CRYPTPROTECT_UI_FORBIDDEN = 0x1
_CRYPTPROTECT_LOCAL_MACHINE = 0x4

_crypt32 = ctypes.WinDLL("crypt32", use_last_error=True)
_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)


class _DataBlob(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.c_void_p)]


_crypt32.CryptProtectData.argtypes = [
    ctypes.POINTER(_DataBlob), wintypes.LPCWSTR, ctypes.POINTER(_DataBlob),
    ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(_DataBlob)]
_crypt32.CryptProtectData.restype = wintypes.BOOL
_crypt32.CryptUnprotectData.argtypes = [
    ctypes.POINTER(_DataBlob), ctypes.POINTER(wintypes.LPWSTR),
    ctypes.POINTER(_DataBlob), ctypes.c_void_p, ctypes.c_void_p,
    wintypes.DWORD, ctypes.POINTER(_DataBlob)]
_crypt32.CryptUnprotectData.restype = wintypes.BOOL
_kernel32.LocalFree.argtypes = [ctypes.c_void_p]
_kernel32.LocalFree.restype = ctypes.c_void_p


def _to_blob(data):
    buffer = ctypes.create_string_buffer(data, len(data))
    blob = _DataBlob(len(data), ctypes.cast(buffer, ctypes.c_void_p))
    return blob, buffer


def _from_blob(blob):
    try:
        return ctypes.string_at(blob.pbData, blob.cbData)
    finally:
        if blob.pbData:
            _kernel32.LocalFree(blob.pbData)


def _dpapi(data, protect, machine_scope=False):
    blob_in, _keepalive = _to_blob(data)
    blob_out = _DataBlob()
    flags = _CRYPTPROTECT_UI_FORBIDDEN
    if machine_scope:
        flags |= _CRYPTPROTECT_LOCAL_MACHINE

    if protect:
        ok = _crypt32.CryptProtectData(
            ctypes.byref(blob_in), "SonicCore", None, None, None,
            flags, ctypes.byref(blob_out))
    else:
        description = wintypes.LPWSTR()
        ok = _crypt32.CryptUnprotectData(
            ctypes.byref(blob_in), ctypes.byref(description), None, None, None,
            flags, ctypes.byref(blob_out))
        if description:
            _kernel32.LocalFree(description)

    if not ok:
        raise OSError(ctypes.get_last_error(), "DPAPI 调用失败")
    return _from_blob(blob_out)


def encrypt_bytes(data, machine_scope=False):
    """把明文模型加密成容器字节（含头部）。"""
    sealed = _dpapi(data, protect=True, machine_scope=machine_scope)
    header = json.dumps({
        "algo": ALGO_DPAPI,
        "scope": "machine" if machine_scope else "user",
        "size": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }, ensure_ascii=False).encode("utf-8")
    return MAGIC + struct.pack(HEADER_LEN_FMT, len(header)) + header + sealed


def decrypt_bytes(container):
    """把容器字节解回明文模型字节。"""
    if not container.startswith(MAGIC):
        raise ValueError("不是模型容器格式（magic 不匹配）")
    offset = len(MAGIC)
    header_len = struct.unpack(HEADER_LEN_FMT, container[offset:offset + 4])[0]
    offset += 4
    header = json.loads(container[offset:offset + header_len].decode("utf-8"))
    offset += header_len
    payload = container[offset:]

    data = _dpapi(payload, protect=False,
                  machine_scope=header.get("scope") == "machine")

    expected = header.get("sha256")
    if expected and hashlib.sha256(data).hexdigest() != expected:
        raise ValueError("解密后的模型校验失败（文件损坏或被篡改）")
    return data


def encrypt_file(src, dst, machine_scope=False):
    with open(src, "rb") as handle:
        raw = handle.read()
    container = encrypt_bytes(raw, machine_scope=machine_scope)
    os.makedirs(os.path.dirname(os.path.abspath(dst)), exist_ok=True)
    with open(dst, "wb") as handle:
        handle.write(container)
    return len(raw), len(container)


def load_model_bytes(path):
    """读加密模型并返回明文 bytes（直接喂给 ort.InferenceSession）。"""
    with open(path, "rb") as handle:
        container = handle.read()
    return decrypt_bytes(container)


def is_container(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(len(MAGIC)) == MAGIC
    except OSError:
        return False


def _main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    command = argv[1]
    if command == "encrypt" and len(argv) >= 4:
        src, dst = argv[2], argv[3]
        machine = "--machine" in argv[4:]
        plain, sealed = encrypt_file(src, dst, machine_scope=machine)
        print(f"已加密: {plain} -> {sealed} 字节 ({os.path.basename(dst)})")
        return 0
    if command == "verify" and len(argv) >= 3:
        data = load_model_bytes(argv[2])
        print(f"解密成功: {len(data)} 字节, sha256={hashlib.sha256(data).hexdigest()[:16]}...")
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
