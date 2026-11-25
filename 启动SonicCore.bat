@echo off
setlocal EnableExtensions
title SonicCore
rem
rem  !! 本文件必须保持 GBK(936) 编码 + CRLF 换行，cmd.exe 才能正确解析中文。
rem  !! 若用 UTF-8 编辑器另存，会导致中文乱码、甚至命令行被截断而启动失败。

rem ============================================================
rem  SonicCore 启动脚本
rem  用法：双击，或 启动SonicCore.bat -t 1 -e  （参数原样转给 main.py）
rem ============================================================

rem ── 切到脚本所在目录──
cd /d "%~dp0"
if not exist "logs" mkdir "logs"

rem ── 查找 Python──
set "PYEXE=%LOCALAPPDATA%\MI\ContinuityApp\runtimes\python-win\python.exe"
if not exist "%PYEXE%" set "PYEXE="
if not defined PYEXE if exist "%~dp0python-win\python.exe" set "PYEXE=%~dp0python-win\python.exe"
if not defined PYEXE for %%I in (python.exe) do set "PYEXE=%%~$PATH:I"

if not defined PYEXE (
    echo.
    echo [错误] 找不到 Python 解释器。已尝试：
    echo     %LOCALAPPDATA%\MI\ContinuityApp\runtimes\python-win\python.exe
    echo     %~dp0python-win\python.exe
    echo     PATH 中的 python.exe
    echo.
    echo 请安装 Python 3.11+，或把 python.exe 放到上面任一位置。
    echo.
    pause
    endlocal & exit /b 1
)

rem ────
"%PYEXE%" -c "import importlib.util as u,sys;sys.exit(0 if all(u.find_spec(m) for m in ('ok','PySide6','qfluentwidgets')) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo [错误] 这个 Python 缺少依赖（ok-script / PySide6 / qfluentwidgets）：
    echo     %PYEXE%
    echo.
    echo 请改用装有依赖的解释器，或先执行：
    echo     "%PYEXE%" -m pip install "ok-script[ocr,qt]"
    echo.
    pause
    endlocal & exit /b 1
)

echo.
echo   SonicCore 游戏辅助启动器
echo   解释器 : %PYEXE%
echo   日志   : %~dp0logs\soniccore.log
echo.

rem ── 启动──
"%PYEXE%" main.py %* 2>"%~dp0logs\launcher_stderr.log"
set "RC=%ERRORLEVEL%"

if not "%RC%"=="0" (
    echo.
    echo ============================================================
    echo   [启动失败] 退出码 %RC%
    echo ============================================================
    if exist "%~dp0logs\launcher_stderr.log" (
        echo.
        echo ---- stderr ----
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath '%~dp0logs\launcher_stderr.log' -Encoding Default -Tail 40"
    )
    if exist "%~dp0logs\soniccore.log" (
        echo.
        echo ---- logs\soniccore.log 末尾 ----
        powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-Content -LiteralPath '%~dp0logs\soniccore.log' -Encoding UTF8 -Tail 40"
    )
    echo.
    pause
)

endlocal & exit /b %RC%
