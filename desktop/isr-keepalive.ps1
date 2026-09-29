# ISR keepalive watchdog.
# Keeps the ISR portal reachable 24/7 on this machine — no matter what else
# restarts. Installed as the Windows Scheduled Task "ISR Keepalive" by
# isr-keepalive-install.ps1, started hidden at every logon. Because it is owned
# by Task Scheduler (not by the ISR launcher, the Freebuff agent, or any other
# app), restarting those apps cannot kill it.
#
# Every 30 seconds it:
#   1. Pins the WSL VM open with a hidden `wsl -- sleep infinity` session.
#      Without it, WSL2 shuts the whole VM down ~60 s after its last client
#      exits — which silently kills the localhost:8080 port-forward
#      ("ERR_CONNECTION_REFUSED") even though the isr container is fine.
#   2. Makes sure the `isr` container is running (Docker's --restart policy
#      covers most cases; this is the safety net for a WSL/dockerd restart).
#   3. Probes http://127.0.0.1:8080/api/health and logs every up/down change.
#
# `desktop\Stop ISR.bat` drops %LOCALAPPDATA%\ISR\stopped.flag, which makes the
# watchdog stand down (no pinning, no auto-start) until the next "Start ISR".
#
# Log: %LOCALAPPDATA%\ISR\keepalive.log

$ErrorActionPreference = 'Continue'
$ProgressPreference    = 'SilentlyContinue'

$Port     = 8080
$AppData  = Join-Path $env:LOCALAPPDATA 'ISR'
$Log      = Join-Path $AppData 'keepalive.log'
$StopFlag = Join-Path $AppData 'stopped.flag'

function Log([string]$msg) {
  try {
    if ((Test-Path $Log) -and ((Get-Item $Log).Length -gt 256KB)) { Clear-Content $Log }
    "[{0:yyyy-MM-dd HH:mm:ss}] {1}" -f (Get-Date), $msg | Out-File -Append -FilePath $Log -Encoding ascii
  } catch {}
}

# Single instance: a second copy of the watchdog simply exits.
$mutex = New-Object System.Threading.Mutex($false, 'ISR-Keepalive-Watchdog')
try { if (-not $mutex.WaitOne(0)) { exit 0 } } catch { }

Log "watchdog started (pid $PID, user $env:USERNAME)"

$state = ''   # '', 'up', 'down', 'docker-down', 'stopped'
$beats = 0

while ($true) {
  try {
    if (Test-Path $StopFlag) {
      if ($state -ne 'stopped') {
        Log 'stop flag present - standing down (run Start ISR to resume watching)'
        $state = 'stopped'
      }
      Start-Sleep -Seconds 30
      continue
    }

    # 1. Pin the WSL VM open (idempotent).
    $ka = @(Get-CimInstance Win32_Process -Filter "Name='wsl.exe'" |
            Where-Object { $_.CommandLine -like '*sleep*infinity*' })
    if ($ka.Count -eq 0) {
      Start-Process wsl.exe -ArgumentList '--','sleep','infinity' -WindowStyle Hidden
      Log 'WSL keepalive re-pinned'
    }

    # 2. Engine container running? (`docker start` on a running container is a
    #    harmless no-op; if the daemon itself is down, bring it up first.)
    $null = & wsl.exe docker start isr 2>$null
    if ($LASTEXITCODE -ne 0) {
      if ($state -ne 'docker-down') {
        Log "docker unreachable (exit $LASTEXITCODE) - starting the daemon inside WSL"
        $state = 'docker-down'
      }
      & wsl.exe -u root sh -lc 'systemctl start docker || service docker start' 2>$null | Out-Null
      Start-Sleep -Seconds 10
      $null = & wsl.exe docker start isr 2>$null
      if ($LASTEXITCODE -eq 0) { Log 'isr container started after daemon recovery' }
    }

    # 3. Health probe.
    $ok = $false
    try {
      $r = Invoke-WebRequest -Uri ("http://127.0.0.1:{0}/api/health" -f $Port) -UseBasicParsing -TimeoutSec 4
      $ok = ($r.StatusCode -eq 200)
    } catch {}

    if ($ok -and $state -ne 'up')            { Log 'portal UP (health 200)' }
    if (-not $ok -and $state -ne 'down')     { Log 'portal DOWN (health probe failed)' }
    if ($ok) { $state = 'up' } elseif ($state -ne 'docker-down') { $state = 'down' }

    $beats++
    if ($beats % 720 -eq 0) { Log "heartbeat: state=$state after $beats cycles" }
  } catch {
    Log "cycle error: $_"
  }
  Start-Sleep -Seconds 30
}
