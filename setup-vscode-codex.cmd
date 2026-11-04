@echo off
rem Double-click to install VS Code + Codex extension + ESP32 upload tools.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0setup-vscode-codex.ps1" %*
pause
