# wwcore 校验壳构建脚本
#
# 流程：
#   1. 计算 nuitka 主程序（wwcore-app.exe）的 SHA256
#   2. 注入到 launcher/src/main.rs 的 EXPECTED_SHA256 常量
#   3. cargo build --release 编译 Rust 启动器
#   4. 把 wwcore.exe 复制到 build\main.dist\
#
# 启动器只做完整性校验 + 拉起子进程，不含反调试/注入/隐藏。
# 前置：Rust GNU 工具链在 PATH 中（本机为 C:\rust\cargo\bin）。

param(
    [string]$PayloadExe = 'wwcore-app.exe',
    [string]$LauncherExe = 'wwcore.exe'
)

$ErrorActionPreference = 'Stop'

$root   = $PSScriptRoot
$dist   = Join-Path $root 'build\main.dist'
$payload = Join-Path $dist $PayloadExe
$srcMain = Join-Path $root 'launcher\src\main.rs'
$cargoBin = 'C:\rust\cargo\bin'

if (-not (Test-Path $payload)) { throw "找不到主程序：$payload（先跑 nuitka 构建）" }

# 1) 真实哈希
$hash = (Get-FileHash -Algorithm SHA256 -Path $payload).Hash.ToLowerInvariant()
Write-Host "Payload SHA256: $hash"

# 2) 注入常量（只替换 PLACEHOLDER 或上次的哈希，不碰其它代码）
$content = Get-Content -Raw -Encoding UTF8 $srcMain
$pattern = 'const EXPECTED_SHA256: &str = "[^"]*";'
if ($content -notmatch $pattern) { throw "main.rs 里找不到 EXPECTED_SHA256 常量" }
$content = [regex]::Replace($content, $pattern, "const EXPECTED_SHA256: &str = `"$hash`";")
# 写回保持 UTF-8 无 BOM
[System.IO.File]::WriteAllText($srcMain, $content, (New-Object System.Text.UTF8Encoding($false)))

# 3) 编译
$env:PATH = "$cargoBin;$env:PATH"
Push-Location (Join-Path $root 'launcher')
try {
    & cargo build --release
    if ($LASTEXITCODE -ne 0) { throw "cargo build 失败，exit=$LASTEXITCODE" }
} finally {
    Pop-Location
}

# 4) 定位产物（优先 .cargo/config.toml 的 target-dir，其次 CARGO_TARGET_DIR 环境变量覆盖值）
$built = $null
foreach ($candidate in @(
    'C:\wuwa-rs-target-launcher\release\wwcore.exe',
    $env:CARGO_TARGET_DIR,
    'C:\rust\target\sonotheca\release\wwcore.exe'
)) {
    if ($candidate -and (Test-Path $candidate)) { $built = $candidate; break }
}
if (-not $built) { throw "找不到编译产物 wwcore.exe" }

Copy-Item -Force $built (Join-Path $dist $LauncherExe)
Write-Host "Launcher OK: $dist\$LauncherExe  (校验壳，sha256 已固化)"

# 还原占位值，避免把私钥式哈希留在源码里被反复 diff
$content = [regex]::Replace($content, $pattern, 'const EXPECTED_SHA256: &str = "PLACEHOLDER";')
[System.IO.File]::WriteAllText($srcMain, $content, (New-Object System.Text.UTF8Encoding($false)))
