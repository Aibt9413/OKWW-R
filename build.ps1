# SonicCore —— Nuitka 构建脚本（双文件模式：wwcore.exe + wwcore-app.exe）
#
# 想要「全部分发成单个 exe」请改用 build_single.ps1（SFX 自解压，
# 保留 SHA256 校验壳 + 模型加密 + 静态混淆）。本脚本保留作本机联调用。
#
# 前置条件（重要）：
#   1. Python 必须装在 **纯 ASCII 路径** 下。中文用户名目录（C:\Users\<中文>\...）
#      会让 Nuitka 的 depends.exe 把路径解析成乱码，构建阶段断言失败：
#        AssertionError: ('c:\\users\\\x04\x04\\...\\python312.dll', ...)
#      当前环境用的是 C:\Python312\python.exe 建的 venv。
#   2. venv 里要装好 requirements-lock.txt + nuitka。
#   3. 环境变量 PYTHONPATH 必须指向 games\wuthering，否则 --include-package=src 找不到。

param(
    [switch]$NoObfuscate   # 关闭静态版权保护注入（默认开启）
)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

$PY = 'C:\wwbuild\venv\Scripts\python.exe'
if (-not (Test-Path $PY)) { $PY = '.\.venv31\Scripts\python.exe' }
if (-not (Test-Path $PY)) { throw "venv 不存在：$PY" }

# 校验 Python 基础路径是 ASCII
$base = & $PY -c "import sys; print(sys.base_prefix)"
if ($base -match '[^\x00-\x7F]') {
    throw "Python 基础路径含非 ASCII 字符，Nuitka 会崩：$base"
}
Write-Host "Python base: $base"

$env:PYTHONPATH = "$PWD\games\wuthering"

# ── 进程名（中性，与 UI 品牌 SonicCore 分离）────────────────────────────
# 对外只暴露 wwcore.exe（Rust 校验壳）；nuitka 主程序用 PAYLOAD_EXE 这个名字。
# 想换名字只改这两行 + launcher/src/main.rs 的 PAYLOAD_NAME。
$LAUNCHER_EXE = 'wwcore.exe'
$PAYLOAD_EXE  = 'wwcore-app.exe'

if (Test-Path 'build') { Remove-Item 'build' -Recurse -Force }

# ── 静态版权保护（源码级，构建前确保已注入，构建后保持）──────────────────
# 注入内容取自本机其它项目术语体系的死代码 + 注释，只改变静态特征，
# 不影响运行时行为。注入是幂等的：已注入的文件会跳过。
# 如需还原干净源码：python tools/obfuscate.py --undo --apply
if (-not $NoObfuscate) {
    & $PY tools/obfuscate.py --apply --level 2
    if ($LASTEXITCODE -ne 0) { throw "静态注入失败" }
    & $PY tools/obfuscate.py --verify
    if ($LASTEXITCODE -ne 0) { throw "静态注入校验失败" }
}

& $PY -m nuitka `
    --standalone `
    --assume-yes-for-downloads `
    --enable-plugin=pyside6 `
    --windows-console-mode=disable `
    --include-package=src `
    --include-package=okunified `
    --include-package=ok `
    --include-package=darkdetect `
    --include-package=qframelesswindow `
    --include-package=shapely `
    --include-package=pyclipper `
    --include-package-data=ok `
    --include-package-data=onnxocr `
    --include-data-dir=games/wuthering/assets=assets `
    --include-data-dir=configs=configs `
    --include-data-dir=icons=icons `
    --include-data-dir=i18n=i18n `
    --include-data-file=games/wuthering/config.py=games/wuthering/config.py `
    --output-dir=build `
    --output-filename=$PAYLOAD_EXE `
    --company-name=SonicCore `
    --product-name=SonicCore `
    --file-version=1.0.0.0 `
    --product-version=1.0.0.0 `
    --file-description=SonicCore `
    main.py

if ($LASTEXITCODE -ne 0) { throw "Nuitka 构建失败，exit=$LASTEXITCODE" }

# ── 构建 Rust 校验壳并注入真实哈希 ────────────────────────────────────────
& "$PSScriptRoot\build_launcher.ps1" -PayloadExe $PAYLOAD_EXE -LauncherExe $LAUNCHER_EXE
if ($LASTEXITCODE -ne 0) { throw "Launcher 构建失败，exit=$LASTEXITCODE" }

$dist = 'build\main.dist'
$size = [math]::Round((Get-ChildItem $dist -Recurse -File -Force | Measure-Object Length -Sum).Sum / 1MB, 0)
$count = (Get-ChildItem $dist -Recurse -File -Force | Measure-Object Length -Sum).Count
Write-Host ('Build OK: ' + $dist + '\' + $LAUNCHER_EXE + '  (' + $size + ' MB / ' + $count + ' files)')
Write-Host 'Source tree keeps static obfuscation (python tools/obfuscate.py --undo --apply to revert).'
