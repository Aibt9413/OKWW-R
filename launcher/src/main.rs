//! wwcore —— 主程序完整性校验启动器（双模式）。
//!
//! 模式 1 · SFX 单文件（默认发布形态）：
//!   归档附加在自身 exe 尾部。运行时校验数据区 SHA256（与构建期固化常量
//!   比对）→ 安全释放到中性临时目录 → 拉起主程序 → 清理 → 转发退出码。
//! 模式 2 · 双文件（兼容本机联调）：
//!   同目录查找 wwcore-app.exe，校验其 SHA256 后拉起。
//!
//! 版权保护职责，非反作弊。明确不做：反调试、进程/线程隐藏、注入、
//! 读游戏内存、hook、伪造硬件输入。启动器不含任何游戏逻辑。

// SFX 解压器完全后台运行：声明 GUI 子系统，避免启动时弹出控制台黑窗口。
// UAC manifest 仍由 build_launcher.ps1 通过 mt.exe 嵌入，不受影响。
#![cfg_attr(windows, windows_subsystem = "windows")]

mod archive;
mod path_guard;
mod python_check;
mod sha256;
mod uac;

use std::env;
use std::ffi::OsString;
use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, ExitCode};
use std::thread;
use std::time::{Duration, SystemTime, UNIX_EPOCH};

/// 被保护的主程序文件名（中性名，与 UI 品牌 SonicCore 分离）。
const PAYLOAD_NAME: &str = "wwcore-app.exe";

/// 双文件模式下由 build_launcher.ps1 注入的真实 SHA256（64 位小写 hex）。
const EXPECTED_SHA256: &str = "PLACEHOLDER";

/// SFX 模式下数据区期望 SHA256（构建期固化；占位值表示未注入→告警放行，便于本机联调）。
const EXPECTED_ARCHIVE_SHA256: &str = "81ac9d5cf898fccecc76be35ffebee4b5dcf361f66f19e4fd07310f15c4600bb";

/// SFX 临时目录前缀（中性，无品牌无上游痕迹）。
const TMP_PREFIX: &str = "wcc_";

fn launcher_exe() -> Option<PathBuf> {
    env::current_exe().ok()
}

fn run_payload(path: &Path, cwd: &Path, args: impl Iterator<Item = OsString>) -> ExitCode {
    let mut cmd = Command::new(path);
    cmd.current_dir(cwd);
    cmd.args(args);
    match cmd.status() {
        Ok(st) => ExitCode::from(st.code().unwrap_or(1) as u8),
        Err(e) => {
            eprintln!("[wwcore] 启动主程序失败: {e}");
            ExitCode::from(3u8)
        }
    }
}

fn hex_eq(actual: &str, expected: &str) -> bool {
    actual.eq_ignore_ascii_case(expected)
}

/// 尽力删除目录，带重试。杀毒软件扫描或上次残留的句柄会短暂锁定临时文件，
/// 立即删除常报 os error 32；重试几次通常就能成功。
fn cleanup_with_retry(dir: &Path) -> bool {
    for _ in 0..8 {
        if !dir.exists() {
            return true;
        }
        if fs::remove_dir_all(dir).is_ok() {
            return true;
        }
        thread::sleep(Duration::from_millis(250));
    }
    !dir.exists()
}

/// 选择释放目录。优先复用固定名（让框架的 cwd 稳定、单实例锁语义不变）；
/// 若固定目录因文件被占用而无法清空，则回退到唯一目录，保证仍能启动。
fn pick_dest(tag: &str) -> PathBuf {
    let base = env::temp_dir();
    let stable = base.join(format!("{TMP_PREFIX}{tag}"));
    if !stable.exists() || cleanup_with_retry(&stable) {
        return stable;
    }
    // 固定目录清不掉（例如被杀软占用）：用唯一目录绕过。
    let pid = std::process::id();
    let nanos = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_nanos())
        .unwrap_or(0);
    eprintln!(
        "[wwcore] 固定临时目录被占用，改用独立目录以避免 os error 32。"
    );
    base.join(format!("{TMP_PREFIX}{tag}_{pid}_{nanos}"))
}

fn run_sfx(self_path: &Path, footer: &archive::Footer, args: impl Iterator<Item = OsString>) -> ExitCode {
    let actual = match archive::verify_data(self_path, footer) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("[wwcore] 读取归档数据区失败: {e}");
            return ExitCode::from(3u8);
        }
    };

    if EXPECTED_ARCHIVE_SHA256 == "PLACEHOLDER" {
        eprintln!(
            "[wwcore] 警告: 归档期望哈希未注入（构建占位值），跳过校验。实际 sha256={actual}"
        );
    } else if !hex_eq(&actual, EXPECTED_ARCHIVE_SHA256) {
        eprintln!("[wwcore] 归档完整性校验失败，拒绝启动。");
        eprintln!("  期望: {EXPECTED_ARCHIVE_SHA256}");
        eprintln!("  实际: {actual}");
        return ExitCode::from(4u8);
    }
    if !hex_eq(&actual, &sha256::hex(&footer.data_sha)) {
        eprintln!("[wwcore] 归档尾部哈希自校验失败，拒绝启动。");
        return ExitCode::from(4u8);
    }

    let entries = match archive::read_entries(self_path, footer) {
        Ok(e) => e,
        Err(e) => {
            eprintln!("[wwcore] 解析归档条目失败: {e}");
            return ExitCode::from(3u8);
        }
    };

    // 临时目录名由数据区哈希前 12 位派生：中性、确定。若被占用则自动回退
    // 到唯一目录，避免"第二次启动"因残留文件被锁而报 os error 32。
    let tag = &actual[..12.min(actual.len())];
    let dest = pick_dest(tag);
    if let Err(e) = archive::extract(self_path, footer, &entries, &dest) {
        eprintln!("[wwcore] 释放归档失败: {e}");
        cleanup_with_retry(&dest);
        return ExitCode::from(3u8);
    }

    let payload = dest.join(PAYLOAD_NAME);
    if !payload.is_file() {
        eprintln!("[wwcore] 释放后未找到主程序: {}", payload.display());
        cleanup_with_retry(&dest);
        return ExitCode::from(3u8);
    }

    let code = run_payload(&payload, &dest, args);
    // 清理临时目录：加密模型容器随归档落到临时目录，退出即删除，不留明文。
    cleanup_with_retry(&dest);
    code
}

fn run_two_file(self_path: &Path, args: impl Iterator<Item = OsString>) -> ExitCode {
    let dir = self_path.parent().unwrap_or(Path::new("."));
    let payload = dir.join(PAYLOAD_NAME);
    if !payload.is_file() {
        eprintln!("[wwcore] 未找到主程序: {}", payload.display());
        return ExitCode::from(3u8);
    }
    let actual = match sha256::hash_file(&payload) {
        Ok(h) => h,
        Err(e) => {
            eprintln!("[wwcore] 读取主程序失败: {e}");
            return ExitCode::from(3u8);
        }
    };
    if EXPECTED_SHA256 == "PLACEHOLDER" {
        eprintln!(
            "[wwcore] 警告: 期望哈希未注入（构建占位值），跳过校验。实际 sha256={actual}"
        );
    } else if !hex_eq(&actual, EXPECTED_SHA256) {
        eprintln!("[wwcore] 主程序完整性校验失败，拒绝启动。");
        eprintln!("  期望: {EXPECTED_SHA256}");
        eprintln!("  实际: {actual}");
        return ExitCode::from(4u8);
    }
    run_payload(&payload, dir, args)
}

fn main() -> ExitCode {
    let self_path = match launcher_exe() {
        Some(p) => p,
        None => {
            eprintln!("[wwcore] 无法确定启动器路径");
            return ExitCode::from(3u8);
        }
    };

    // 运行前提校验 1：安装路径必须是纯 ASCII（英文目录）。
    if !path_guard::ensure_ascii_path(&self_path) {
        return ExitCode::from(6u8);
    }

    // 运行前提校验 2：必须以管理员身份运行。非管理员时请求标准 UAC 提权，
    // 提权进程会重新走完整流程；拒绝/失败则明确退出（不做任何动态对抗）。
    let args: Vec<OsString> = env::args_os().skip(1).collect();
    match uac::ensure_admin(&self_path, &args) {
        Ok(true) => {}
        Ok(false) => return ExitCode::from(0u8),
        Err(message) => {
            eprintln!("[wwcore] {message}");
            return ExitCode::from(5u8);
        }
    }

    // 运行前提提示 3：系统 Python 检测。单文件自带运行时，这里只做环境提示，
    // 缺失时弹窗询问是否打开官方下载页，不阻塞启动、不做任何自动安装。
    python_check::prompt_if_missing();

    let footer = match archive::read_footer(&self_path) {
        Ok(f) => f,
        Err(e) => {
            eprintln!("[wwcore] 读取自身失败: {e}");
            return ExitCode::from(3u8);
        }
    };

    match footer {
        Some(f) => run_sfx(&self_path, &f, args.into_iter()),
        None => run_two_file(&self_path, args.into_iter()),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn payload_name_is_neutral() {
        assert!(!PAYLOAD_NAME.to_ascii_lowercase().contains("ok"));
        assert!(!PAYLOAD_NAME.to_ascii_lowercase().contains("sonic"));
    }

    #[test]
    fn tmp_prefix_is_neutral() {
        assert!(!TMP_PREFIX.to_ascii_lowercase().contains("ok"));
        assert!(!TMP_PREFIX.to_ascii_lowercase().contains("sonic"));
    }

    #[test]
    fn hex_eq_is_case_insensitive() {
        assert!(hex_eq("ABCD", "abcd"));
        assert!(!hex_eq("abcd", "abce"));
    }
}
