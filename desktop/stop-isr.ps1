# ISR — stop the local engine (the `isr` container).
# Also drops stopped.flag so the "ISR Keepalive" watchdog stands down instead of
# restarting the engine behind your back. "Start ISR" clears the flag and the
# watchdog resumes watching.
$AppData = Join-Path $env:LOCALAPPDATA 'ISR'
New-Item -ItemType Directory -Force -Path $AppData | Out-Null
Set-Content -Path (Join-Path $AppData 'stopped.flag') -Value "stopped $([DateTime]::Now)" -Encoding ascii

wsl docker stop isr 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
  Write-Host "ISR engine stopped. (Keepalive watchdog paused until the next Start ISR.)"
} else {
  Write-Host "ISR engine was not running. (Keepalive watchdog paused until the next Start ISR.)"
}
