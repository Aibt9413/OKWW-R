//! 安装路径校验：启动器所在路径必须是纯 ASCII（英文目录）。
//!
//! 与主程序一致的运行前提校验，不做进程隐藏/反调试。非 ASCII 路径在
//! 打包工具链与 Qt/ONNX Runtime 上都可能出编码问题，因此直接拒绝启动。

use std::ffi::c_void;
use std::os::windows::ffi::OsStrExt;
use std::path::Path;
use std::ptr;

type LPCWSTR = *const u16;

#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(hwnd: *mut c_void, text: LPCWSTR, caption: LPCWSTR, msg_type: u32) -> i32;
}

const MB_OK: u32 = 0x0000_0000;
const MB_ICONERROR: u32 = 0x0000_0010;

fn wide_literal(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

fn path_has_non_ascii(path: &Path) -> bool {
    path.as_os_str().encode_wide().any(|unit| unit > 0x7F)
}

/// 路径全 ASCII 返回 true；否则弹窗提示并返回 false。
pub fn ensure_ascii_path(path: &Path) -> bool {
    if !path_has_non_ascii(path) {
        return true;
    }

    let text = wide_literal(
        "当前安装路径包含中文或非 ASCII 字符，程序无法在此路径下稳定运行。\n\n请将 wwcore.exe 移动到纯英文路径后重试，例如：\nC:\\wwbuild\\dist\\wwcore.exe",
    );
    let caption = wide_literal("路径不合法");
    unsafe {
        MessageBoxW(
            ptr::null_mut(),
            text.as_ptr(),
            caption.as_ptr(),
            MB_OK | MB_ICONERROR,
        );
    }
    eprintln!(
        "[wwcore] 安装路径含非 ASCII 字符，拒绝启动: {}",
        path.display()
    );
    false
}

/// 非 Windows 平台联调用（发布目标为 Windows）。
#[cfg(not(windows))]
pub fn ensure_ascii_path(_path: &Path) -> bool {
    true
}
