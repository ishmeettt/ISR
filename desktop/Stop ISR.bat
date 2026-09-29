@echo off
rem ISR desktop app — stop the engine container.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0stop-isr.ps1"
pause
