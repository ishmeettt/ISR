@echo off
rem ISR desktop app — starts the engine and opens the app window.
start "ISR" /min powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "%~dp0start-isr.ps1"
