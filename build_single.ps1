# SonicCore —— 单 exe 发布构建（SFX）
#
# 流程：
#   1. PyInstaller --onedir --windowed 产出 build_pyi\wwcore-app\（含主程序 + 依赖 + 数据）
#   2. 计算数据区 SHA256，固化进 launcher/src/main.rs 的 EXPECTED_ARCHIVE_SHA256
#   3. cargo build --release 重新编译 SFX launcher（常量编进 exe）
#   4. pack_single.py 把 launcher + 整个目录打包成单个 wwcore.exe
#   5. 还原 main.rs 占位常量
#
# 保留特性：SHA256 完整性校验壳、模型 DPAPI 加密（不落明文）、进程名中性、
# 静态混淆、管理员权限校验、纯英文安装路径校验。
# 明确不做：反调试、注入、hook、读游戏内存、伪造硬件输入。
# 前置：C:\wwbuild\venv（PyInstaller）+ Rust GNU 工具链（C:\rust\cargo\bin）。
# 输出：C:\wwbuild\dist\wwcore.exe（纯英文路径）。

param(
    [string]$Python = 'C:\wwbuild\venv\Scripts\python.exe',
    [switch]$SkipPayload   # 已有 build_pyi\wwcore-app 时跳过 PyInstaller
)

$ErrorActionPreference = 'Continue'
Set-Location $PSScriptRoot

$PY = $Python
if (-not (Test-Path $PY)) {
    $fallback = '.\.venv31\Scripts\python.exe'
    if (Test-Path $fallback) { $PY = $fallback }
}
if (-not (Test-Path $PY)) { throw "venv 不存在：$PY" }

$env:PYTHONPATH = "$PWD\games\wuthering"

$LAUNCHER_EXE = 'wwcore.exe'
$PAYLOAD_EXE  = 'wwcore-app.exe'
$OUT_DIR      = 'C:\wwbuild\dist'
$PYI_DIR      = 'build_pyi'
$WORK_DIR     = 'build_pyi_work'
$SPEC_DIR     = 'build_pyi_spec'
$dist         = Join-Path $PYI_DIR $PAYLOAD_EXE

# ── 静态版权保护：确保源码已注入（幂等）──────────────────────────────────
& $PY tools/obfuscate.py --apply --level 2
if ($LASTEXITCODE -ne 0) { throw "静态注入失败" }
& $PY tools/obfuscate.py --verify
if ($LASTEXITCODE -ne 0) { throw "静态注入校验失败" }

try {
    # ── 1. PyInstaller onedir ──────────────────────────────────────────────
    if (-not $SkipPayload) {
        $root = $PSScriptRoot
        $addAssets = "$root\games\wuthering\assets;assets"
        # 游戏项目自身的 assets/i18n/config 必须放在 _internal\games\wuthering 下：
        # compat.load_game_config() 按 __file__ 定位这个目录，缺一个都会导致整份
        # 任务配置被跳过（侧边栏任务全部消失）。目标一律用正斜杠，避免被当成目录。
        $addGameAssets = "$root\games\wuthering\assets;games/wuthering/assets"
        $addGameI18n = "$root\games\wuthering\i18n;games/wuthering/i18n"
        $addGameConfig = "$root\games\wuthering\config.py;games/wuthering"
        $addConfigs = "$root\configs;configs"
        $addIcons = "$root\icons;icons"
        $addI18n = "$root\i18n;i18n"

        & $PY -m PyInstaller --noconfirm --onedir --windowed `
            --name $PAYLOAD_EXE `
            --distpath $PYI_DIR --workpath $WORK_DIR --specpath $SPEC_DIR `
            --add-data $addAssets --add-data $addGameAssets --add-data $addGameI18n `
            --add-data $addConfigs --add-data $addIcons --add-data $addI18n `
            --add-data $addGameConfig `
            --collect-submodules src --collect-submodules ok --collect-submodules okunified `
            --collect-all onnxocr --collect-all qfluentwidgets --collect-all qframelesswindow `
            --collect-all darkdetect --collect-all shapely --collect-all pyclipper `
            main.py
        if ($LASTEXITCODE -ne 0) { throw "PyInstaller 构建失败，exit=$LASTEXITCODE" }
    }
    if (-not (Test-Path (Join-Path $dist $PAYLOAD_EXE))) { throw "找不到主程序：$dist\$PAYLOAD_EXE" }

    # ── 2~4. 编译 SFX launcher + 打包单文件 ────────────────────────────────
    $cargoBin = 'C:\rust\cargo\bin'
    $env:PATH = "$cargoBin;$env:PATH"
    $env:CARGO_TARGET_DIR = 'C:\wuwa-rs-target-launcher'
    # 显式指定 windres，规避中文用户名下 LOCALAPPDATA 编码问题，确保
    # requireAdministrator manifest 稳定嵌入（双击直接弹 UAC，不再闪退）。
    $windres = Get-ChildItem (Join-Path $env:LOCALAPPDATA 'Nuitka\Nuitka\Cache\downloads\gcc') `
        -Recurse -Filter windres.exe -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($windres) { $env:WINDRES_PATH = $windres.FullName }
    $srcMain = Join-Path $PSScriptRoot 'launcher\src\main.rs'
    $mainBackup = Join-Path $env:TEMP 'wwcore_main_rs_backup.txt'

    Copy-Item -Force $srcMain $mainBackup

    function Build-Launcher {
        $manifest = Join-Path $PSScriptRoot 'launcher\Cargo.toml'
        & cargo build --release --manifest-path $manifest
        if ($LASTEXITCODE -ne 0) { throw "cargo build 失败，exit=$LASTEXITCODE" }
        $exe = Join-Path $env:CARGO_TARGET_DIR 'release\wwcore.exe'
        # 强制校验 manifest 已嵌入：cargo 的 build-script 缓存可能在多次构建间
        # 链接到旧的"无 manifest"产物，导致双击因非管理员而闪退。缺了就硬失败。
        $bytes = [System.IO.File]::ReadAllBytes($exe)
        $head = [System.Text.Encoding]::ASCII.GetString($bytes, 0, [Math]::Min(400000, $bytes.Length))
        if (-not $head.Contains('requireAdministrator')) {
            throw "启动器未嵌入 requireAdministrator manifest！请清理 $env:CARGO_TARGET_DIR 后重建，并确认 WINDRES_PATH=$env:WINDRES_PATH"
        }
        return $exe
    }

    try {
        $baseLauncher = Build-Launcher
        & $PY tools/pack_single.py --dist $dist --launcher $baseLauncher `
            --out (Join-Path $OUT_DIR $LAUNCHER_EXE) --inject-hash
        if ($LASTEXITCODE -ne 0) { throw "首次打包失败" }

        $sealedLauncher = Build-Launcher
        & $PY tools/pack_single.py --dist $dist --launcher $sealedLauncher `
            --out (Join-Path $OUT_DIR $LAUNCHER_EXE)
        if ($LASTEXITCODE -ne 0) { throw "二次打包失败" }

        & $PY tools/pack_single.py --verify (Join-Path $OUT_DIR $LAUNCHER_EXE)
        if ($LASTEXITCODE -ne 0) { throw "单文件校验失败" }
    }
    finally {
        Copy-Item -Force $mainBackup $srcMain
        Remove-Item -Force $mainBackup -ErrorAction SilentlyContinue
    }

    $out = Join-Path $OUT_DIR $LAUNCHER_EXE
    $size = [math]::Round((Get-Item $out).Length / 1MB, 1)
    Write-Host "Build OK: $out  ($size MB, single executable)"
    Write-Host "  - SFX 校验壳（SHA256 固化）"
    Write-Host "  - 模型 DPAPI 加密保留，运行时内存解密"
    Write-Host "  - 静态混淆已注入源码（undo: python tools/obfuscate.py --undo --apply）"
    Write-Host "  - 运行前提：纯英文安装路径 + 管理员权限（UAC）"
    Write-Host "  - 环境提示：系统无 Python 时弹窗，可选打开官方下载页（不阻塞启动）"
}
catch {
    Write-Error $_
    exit 1
}
