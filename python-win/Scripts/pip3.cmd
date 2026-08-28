@echo off
setlocal
set "PYROOT=%~dp0.."
"%PYROOT%\python.exe" -m pip %*
