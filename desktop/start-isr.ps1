# ISR desktop launcher.
# Starts the local engine (the `isr` Docker container via WSL) and opens the
# app in a native window — no browser chrome, its own taskbar icon. The UI is
# rendered by the OS's embedded web view, the same approach as VS Code/Slack;
# nothing is installed and everything runs on this machine.
#
# Double-click "Start ISR.bat" (same folder) to use this. Do not edit $Port
# unless you also change the container's published port.
$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Windows.Forms

$Port = 8080
$Url  = "http://127.0.0.1:$Port/"
$AppData = Join-Path $env:LOCALAPPDATA "ISR"
New-Item -ItemType Directory -Force -Path $AppData | Out-Null
$log = Join-Path $AppData "launcher.log"

function Log([string]$msg) { "$([DateTime]::Now) $msg" | Out-File -Append $log }
function Fail([string]$msg) {
  Log "FAIL: $msg"
  [System.Windows.Forms.MessageBox]::Show("$msg`n`nDetails: $log", "ISR", "OK", "Error") | Out-Null
  exit 1
}
# Resuming: clear the stop marker so the keepalive watchdog watches again.
Remove-Item (Join-Path $AppData "stopped.flag") -ErrorAction SilentlyContinue
Log "launching ISR desktop app"

# 1. Is Docker (inside WSL) reachable?
$names = (wsl docker ps -a --format "{{.Names}}" 2>&1 | ForEach-Object { "$_".Trim() })
if ($LASTEXITCODE -ne 0) {
  Fail "Docker is not available. Start WSL (open an Ubuntu terminal once) and try again. If this keeps failing, run 'wsl docker ps' yourself and read the error."
}

# 2. Engine container: start it, or create it on first run.
if ($names -contains "isr") {
  wsl docker start isr | Out-Null
  Log "engine container 'isr' started (or was already running)"
} else {
  wsl docker run -d --name isr -p "${Port}:8000" -v isr_data:/data -v isr_repos:/repos --restart unless-stopped isr-offline | Out-Null
  if ($LASTEXITCODE -ne 0) {
    Fail "Could not create the ISR container. Is the 'isr-offline' image built? See README, section 'Desktop app (Windows)'."
  }
  Log "engine container 'isr' created with persistent volume isr_data"
}

# 3. Wait until the engine answers (first boot also seeds the database).
$ready = $false
foreach ($i in 1..60) {
  try {
    $r = Invoke-WebRequest -Uri "http://127.0.0.1:$Port/api/health" -UseBasicParsing -TimeoutSec 2
    if ($r.StatusCode -eq 200) { $ready = $true; break }
  } catch { Start-Sleep -Milliseconds 500 }
}
if (-not $ready) {
  Fail "The ISR engine did not come up on port $Port. Check the logs:  wsl docker logs isr"
}
Log "engine healthy on port $Port"

# 3b. Keepalive: the "ISR Keepalive" scheduled task owns the hidden WSL pin and
# watches the portal every 30 s — it survives app restarts, unlike a pin
# started from here (which died whenever the launching app restarted). Make
# sure it's installed and running; it needs no administrator rights.
$task = Get-ScheduledTask -TaskName 'ISR Keepalive' -ErrorAction SilentlyContinue
if ($task) {
  if ($task.State -ne 'Running') { Start-ScheduledTask -TaskName 'ISR Keepalive' }
  Log "keepalive watchdog ensured via scheduled task (state: $($task.State))"
} else {
  & (Join-Path $PSScriptRoot 'isr-keepalive-install.ps1') | Out-Null
  Log "keepalive watchdog installed and started (scheduled task)"
}

# 4. Open the app window (embedded web view, app mode — no address bar).
$browsers = @(
  "$env:ProgramFiles\Microsoft\Edge\Application\msedge.exe",
  "${env:ProgramFiles(x86)}\Microsoft\Edge\Application\msedge.exe",
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "$env:LOCALAPPDATA\Google\Chrome\Application\chrome.exe",
  "$env:ProgramFiles\BraveSoftware\Brave-Browser\Application\brave.exe"
)
$browser = $browsers | Where-Object { Test-Path $_ } | Select-Object -First 1
if ($browser) {
  $profile = Join-Path $AppData "AppProfile"
  Start-Process $browser -ArgumentList @(
    "--app=$Url",
    "--user-data-dir=""$profile""",
    "--window-size=1280,860",
    "--no-first-run",
    "--no-default-browser-check"
  )
  Log "app window opened via $browser"
} else {
  Start-Process $Url   # last resort: default browser
  Log "no Edge/Chrome/Brave found; opened default browser"
}
