//! 系统 Python 环境检测与安装提示。
//!
//! 单文件包已自带 Python 运行时和全部依赖，这里只给用户系统环境做提示，
//! 不阻塞启动。检测到缺失时弹窗，用户可选打开官方下载页。
//! 这是环境提示，不是动态对抗，也不读取游戏进程。

#[cfg(windows)]
use std::env;
#[cfg(windows)]
use std::ffi::c_void;
#[cfg(windows)]
use std::fs;
#[cfg(windows)]
use std::path::PathBuf;
#[cfg(windows)]
use std::process::Command;
#[cfg(windows)]
use std::ptr;

#[cfg(windows)]
type LPCWSTR = *const u16;

#[cfg(windows)]
#[link(name = "user32")]
extern "system" {
    fn MessageBoxW(hwnd: *mut c_void, text: LPCWSTR, caption: LPCWSTR, msg_type: u32) -> i32;
}

#[cfg(windows)]
#[link(name = "shell32")]
extern "system" {
    fn ShellExecuteW(
        hwnd: *mut c_void,
        operation: LPCWSTR,
        file: LPCWSTR,
        parameters: LPCWSTR,
        directory: LPCWSTR,
        show_cmd: i32,
    ) -> *mut c_void;
}

#[cfg(windows)]
const MB_YESNO: u32 = 0x0000_0004;
#[cfg(windows)]
const MB_ICONINFORMATION: u32 = 0x0000_0040;
#[cfg(windows)]
const MB_DEFBUTTON2: u32 = 0x0000_0200;
#[cfg(windows)]
const IDYES: i32 = 6;

#[cfg(windows)]
const DOWNLOAD_URL: &str = "https://www.python.org/downloads/windows/";

#[cfg(windows)]
fn wide(text: &str) -> Vec<u16> {
    text.encode_utf16().chain(std::iter::once(0)).collect()
}

#[cfg(windows)]
fn exists_in_path(exe: &str) -> bool {
    match Command::new("where.exe").arg(exe).output() {
        Ok(out) => out.status.success() && !out.stdout.is_empty(),
        Err(_) => false,
    }
}

#[cfg(windows)]
fn registry_has_python() -> bool {
    for hive in ["HKLM", "HKCU"] {
        for sub in [
            r"SOFTWARE\Python\PythonCore",
            r"SOFTWARE\WOW6432Node\Python\PythonCore",
        ] {
            let key = format!("{hive}\\{sub}");
            if let Ok(out) = Command::new("reg.exe").args(["query", &key]).output() {
                if out.status.success() {
                    let text = String::from_utf8_lossy(&out.stdout);
                    if text.contains("PythonCore") {
                        return true;
                    }
                }
            }
        }
    }
    false
}

#[cfg(windows)]
fn common_install_paths() -> bool {
    let mut candidates: Vec<PathBuf> = Vec::new();
    if let Ok(local) = env::var("LOCALAPPDATA") {
        let root = PathBuf::from(local).join("Programs").join("Python");
        if let Ok(entries) = fs::read_dir(root) {
            for entry in entries.flatten() {
                candidates.push(entry.path().join("python.exe"));
            }
        }
    }
    for minor in 6..=14 {
        candidates.push(PathBuf::from(format!("C:\\Python3{minor}\\python.exe")));
    }
    candidates.iter().any(|path| path.is_file())
}

/// 系统 PATH / 注册表 / 常见安装目录任一处找到 Python 即返回 true。
#[cfg(windows)]
pub fn system_python_installed() -> bool {
    exists_in_path("python.exe")
        || exists_in_path("python3.exe")
        || registry_has_python()
        || common_install_paths()
}

#[cfg(not(windows))]
pub fn system_python_installed() -> bool {
    true
}

#[cfg(windows)]
fn open_download_page() {
    let operation = wide("open");
    let url = wide(DOWNLOAD_URL);
    unsafe {
        ShellExecuteW(
            ptr::null_mut(),
            operation.as_ptr(),
            url.as_ptr(),
            ptr::null(),
            ptr::null(),
            1,
        );
    }
}

/// 缺失时弹一次提示；用户可选择打开下载页。不影响主程序继续启动。
/// 设置 WWCORE_SKIP_PYTHON_CHECK 可静默跳过（用于自动化构建验证）。
#[cfg(windows)]
pub fn prompt_if_missing() {
    if env::var_os("WWCORE_SKIP_PYTHON_CHECK").is_some() {
        return;
    }
    if system_python_installed() {
        return;
    }

    let text = wide(
        "未在系统中检测到 Python。\n\n\
         本程序已内置运行环境和全部依赖，不安装 Python 也能正常使用。\n\
         如果需要运行外部 Python 脚本或进行开发，建议安装 Python 3.12。\n\n\
         是否现在打开 Python 下载页面？",
    );
    let caption = wide("Python 环境提示");
    let answer = unsafe {
        MessageBoxW(
            ptr::null_mut(),
            text.as_ptr(),
            caption.as_ptr(),
            MB_YESNO | MB_ICONINFORMATION | MB_DEFBUTTON2,
        )
    };
    if answer == IDYES {
        open_download_page();
    }
}

#[cfg(not(windows))]
pub fn prompt_if_missing() {}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn detection_does_not_panic() {
        // 只验证检测路径不会崩；不同机器结果不同，因此不断言具体值。
        let _ = system_python_installed();
    }
}
