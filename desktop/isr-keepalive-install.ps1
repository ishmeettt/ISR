# ISR keepalive installer.
# Registers the "ISR Keepalive" scheduled task that keeps the portal reachable
# 24/7. Re-run any time; -Force replaces an existing task.
#
# Why a scheduled task: the old fix pinned WSL from inside the ISR launcher, so
# every restart of an app (or of the Freebuff agent) killed the pin and the
# portal dropped with it. A task owned by Windows Task Scheduler starts at every
# logon, is re-launched every 5 minutes if anything kills it, and Windows
# restarts it if it fails — nothing outside Windows can end it permanently.
#
# Registered from raw task XML because the PowerShell 5.1 cmdlets cannot attach
# a Repetition interval to a logon trigger (CIM quirk on this build).
# Per-user task: needs no administrator rights.
$ErrorActionPreference = 'Stop'

$dir      = $PSScriptRoot
$taskName = 'ISR Keepalive'
$vbs      = Join-Path $dir 'isr-keepalive.vbs'
if (-not (Test-Path $vbs)) { throw "missing $vbs" }

$xml = @"
<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>ISR keepalive: pins the WSL VM open, keeps the isr container running, and self-heals the portal on http://127.0.0.1:8080. Log: %LOCALAPPDATA%\ISR\keepalive.log</Description>
  </RegistrationInfo>
  <Triggers>
    <LogonTrigger>
      <Enabled>true</Enabled>
      <UserId>$env:USERNAME</UserId>
      <Repetition>
        <Interval>PT5M</Interval>
        <StopAtDurationEnd>false</StopAtDurationEnd>
      </Repetition>
    </LogonTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <UserId>$env:USERNAME</UserId>
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <AllowHardTerminate>false</AllowHardTerminate>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>
    <AllowStartOnDemand>true</AllowStartOnDemand>
    <Enabled>true</Enabled>
    <Hidden>true</Hidden>
    <RunOnlyIfIdle>false</RunOnlyIfIdle>
    <WakeToRun>false</WakeToRun>
    <ExecutionTimeLimit>PT0S</ExecutionTimeLimit>
    <Priority>7</Priority>
    <RestartOnFailure>
      <Interval>PT1M</Interval>
      <Count>3</Count>
    </RestartOnFailure>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>wscript.exe</Command>
      <Arguments>"$vbs"</Arguments>
    </Exec>
  </Actions>
</Task>
"@

Register-ScheduledTask -TaskName $taskName -Xml $xml -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Scheduled task '$taskName' installed and started."
Write-Host "The watchdog now keeps the portal up at every logon and heals outages within ~1 minute."
Write-Host "Log: $env:LOCALAPPDATA\ISR\keepalive.log"
