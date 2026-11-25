//! 把 requireAdministrator manifest 嵌入 exe 资源段。
//! Windows 加载器在进程创建前就完成提权，避免运行时二次拉起导致的闪退。

use std::env;
use std::path::PathBuf;
use std::process::Command;

fn find_windres() -> Option<PathBuf> {
    // 0. 显式指定（构建脚本传入，规避中文用户名环境变量编码问题）
    if let Ok(p) = env::var("WINDRES_PATH") {
        let path = PathBuf::from(&p);
        if path.is_file() {
            return Some(path);
        }
    }
    // 1. PATH 里直接找
    if let Ok(out) = Command::new("windres").arg("--version").output() {
        if out.status.success() {
            return Some(PathBuf::from("windres"));
        }
    }
    // 2. Nuitka 下载的 MinGW 工具链（本机已知位置）
    let base = PathBuf::from(env::var("LOCALAPPDATA").ok()?)
        .join("Nuitka")
        .join("Nuitka")
        .join("Cache")
        .join("downloads")
        .join("gcc");
    if let Ok(entries) = std::fs::read_dir(&base) {
        for e in entries.flatten() {
            let p = e.path().join("mingw64").join("bin").join("windres.exe");
            if p.is_file() {
                return Some(p);
            }
        }
    }
    // 3. 兜底：LOCALAPPDATA 环境变量缺失时，用 C:\Users\<用户>\AppData\Local
    if let Ok(home) = env::var("USERPROFILE") {
        let base = PathBuf::from(home)
            .join("AppData")
            .join("Local")
            .join("Nuitka")
            .join("Nuitka")
            .join("Cache")
            .join("downloads")
            .join("gcc");
        if let Ok(entries) = std::fs::read_dir(&base) {
            for e in entries.flatten() {
                let p = e.path().join("mingw64").join("bin").join("windres.exe");
                if p.is_file() {
                    return Some(p);
                }
            }
        }
    }
    None
}

fn main() {
    println!("cargo:rerun-if-changed=app.manifest");
    println!("cargo:rerun-if-changed=app.rc");
    println!("cargo:rerun-if-changed=build.rs");
    println!("cargo:rerun-if-env-changed=WINDRES_PATH");

    // 必须嵌入 requireAdministrator manifest。找不到 windres 就硬失败，
    // 绝不静默产出无 manifest 的 exe（否则双击会因非管理员而闪退）。
    let windres = match find_windres() {
        Some(p) => p,
        None => {
            eprintln!("build.rs: 未找到 windres，无法嵌入管理员权限 manifest。请设置 WINDRES_PATH。");
            std::process::exit(1);
        }
    };

    let out_dir = PathBuf::from(env::var("OUT_DIR").expect("OUT_DIR"));
    let res = out_dir.join("app_manifest.res");
    let status = Command::new(&windres)
        .arg("-i")
        .arg("app.rc")
        .arg("-o")
        .arg(&res)
        .arg("-O")
        .arg("coff")
        .status()
        .unwrap_or_else(|e| {
            eprintln!("build.rs: windres 执行失败: {e}");
            std::process::exit(1);
        });
    if !status.success() {
        eprintln!("build.rs: windres 编译 app.rc 失败 (status={status})");
        std::process::exit(1);
    }

    println!("cargo:rustc-link-arg={}", res.display());
}
