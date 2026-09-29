' ISR keepalive watchdog launcher.
' Runs the PowerShell watchdog (isr-keepalive.ps1, same folder) with no window
' at all — no console flash, nothing in the taskbar. Used as the action of the
' "ISR Keepalive" scheduled task.
Set fso = CreateObject("Scripting.FileSystemObject")
dir = fso.GetParentFolderName(WScript.ScriptFullName)
CreateObject("WScript.Shell").Run _
  "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & dir & "\isr-keepalive.ps1""", 0, False
