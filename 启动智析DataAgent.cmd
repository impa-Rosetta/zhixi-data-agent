@echo off
chcp 65001 >nul
title 智析 Data Agent 启动器
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\start-zhixi.ps1"
if errorlevel 1 (
  echo.
  echo 启动失败，请查看上方提示。按任意键关闭窗口。
  pause >nul
)
