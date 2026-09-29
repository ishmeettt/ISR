# Create (or refresh) the "ISR" desktop shortcut.
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path   # .../ISR/desktop
$repo = Split-Path -Parent $root                          # .../ISR

$desktop = [Environment]::GetFolderPath("Desktop")
$lnkPath = Join-Path $desktop "ISR.lnk"

$ws = New-Object -ComObject WScript.Shell
$lnk = $ws.CreateShortcut($lnkPath)
$lnk.TargetPath = (Join-Path $root "Start ISR.bat")
$lnk.WorkingDirectory = $root
$lnk.IconLocation = (Join-Path $root "assets\isr-icon.ico")
$lnk.Description = "ISR - Intelligent Submission & Review (local desktop app)"
$lnk.WindowStyle = 7   # minimized: the .bat only bootstraps; the real window appears on its own
$lnk.Save()

Write-Host "Shortcut created: $lnkPath"
