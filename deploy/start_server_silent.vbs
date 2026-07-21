' SmartWagers — silent server startup (no CMD window).
' Pin this to the desktop or put a shortcut in Startup.
'
' Runs start_server.bat hidden. That script:
'   1. Checks/starts Memurai (PING)
'   2. Checks/starts SmartWagers-Daphne and waits until :8080 responds
'   3. Checks/starts the local print agent
'   4. Opens Chrome only when Daphne is ready
'
' Errors are written to C:\SmartWagers\logs\start_server_silent.log

Option Explicit
Dim sh, fso, scriptDir, batPath, logDir, logPath, env, exitCode, ts
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_server.bat"
logDir = "C:\SmartWagers\logs"
logPath = logDir & "\start_server_silent.log"

If Not fso.FolderExists(logDir) Then
  On Error Resume Next
  fso.CreateFolder "C:\SmartWagers"
  fso.CreateFolder logDir
  On Error GoTo 0
End If

If Not fso.FileExists(batPath) Then
  AppendLog "ERROR: start_server.bat not found at " & batPath
  WScript.Quit 1
End If

Set env = sh.Environment("PROCESS")
env("SMARTWAGERS_SILENT") = "1"

AppendLog "Starting: " & batPath
' 0 = hidden, True = wait so we can log the exit code
exitCode = sh.Run("""" & batPath & """", 0, True)
AppendLog "Finished with exit code " & exitCode
WScript.Quit exitCode

Sub AppendLog(msg)
  Dim stream
  On Error Resume Next
  ts = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) _
     & " " & Right("0" & Hour(Now), 2) & ":" & Right("0" & Minute(Now), 2) _
     & ":" & Right("0" & Second(Now), 2)
  Set stream = fso.OpenTextFile(logPath, 8, True)
  stream.WriteLine ts & " " & msg
  stream.Close
  On Error GoTo 0
End Sub
