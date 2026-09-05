' SmartWagers - start print agent with no console window.
' Prefers bundled python\pythonw.exe (offline embeddable runtime).
' Falls back to PATH pythonw / pyw / python.
' Errors are appended to print_agent_silent.log (Python also writes there on crash).

Option Explicit
Dim sh, fso, scriptDir, logPath, ts, agentPy, ok
Dim bundledPythonw, bundledPython
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
logPath = scriptDir & "\print_agent_silent.log"
agentPy = scriptDir & "\print_agent.py"
bundledPythonw = scriptDir & "\python\pythonw.exe"
bundledPython = scriptDir & "\python\python.exe"
sh.CurrentDirectory = scriptDir

If Not fso.FileExists(agentPy) Then
  AppendLog "ERROR: print_agent.py not found in " & scriptDir
  WScript.Quit 1
End If

AppendLog "Launch requested for " & agentPy

If Not SyntaxCheckOk() Then
  AppendLog "ERROR: print_agent.py failed syntax check (see message above)"
  WScript.Quit 1
End If

' 0 = hidden window, False = do not wait
ok = False
If fso.FileExists(bundledPythonw) Then
  If TryRunQuoted(bundledPythonw, """" & agentPy & """", False) Then ok = True
End If
If Not ok And fso.FileExists(bundledPython) Then
  If TryRunQuoted(bundledPython, """" & agentPy & """", False) Then ok = True
End If
If Not ok And TryRunPython("pythonw """ & agentPy & """", False) Then ok = True
If Not ok And TryRunPython("pyw """ & agentPy & """", False) Then ok = True
If Not ok And TryRunPython("python """ & agentPy & """", False) Then ok = True

If Not ok Then
  AppendLog "ERROR: could not start print agent - bundled/system python not found or failed to launch"
  WScript.Quit 1
End If

AppendLog "Print agent process started (check http://127.0.0.1:8765/health for version)"
WScript.Quit 0

Function SyntaxCheckOk()
  If fso.FileExists(bundledPython) Then
    SyntaxCheckOk = TryRunQuoted(bundledPython, "-m py_compile """ & agentPy & """", True)
    Exit Function
  End If
  SyntaxCheckOk = TryRunPython("python -m py_compile """ & agentPy & """", True)
End Function

Function TryRunQuoted(exePath, args, waitForExit)
  On Error Resume Next
  Err.Clear
  Dim exitCode, cmd
  cmd = """" & exePath & """ " & args
  exitCode = sh.Run(cmd, 0, waitForExit)
  If Err.Number <> 0 Then
    AppendLog "WARN: " & cmd & " -> " & Err.Description
    TryRunQuoted = False
    Exit Function
  End If
  If waitForExit And exitCode <> 0 Then
    AppendLog "ERROR: " & cmd & " exited with code " & exitCode
    TryRunQuoted = False
    Exit Function
  End If
  AppendLog "OK: " & cmd
  TryRunQuoted = True
  On Error GoTo 0
End Function

Function TryRunPython(cmd, waitForExit)
  On Error Resume Next
  Err.Clear
  Dim exitCode
  exitCode = sh.Run(cmd, 0, waitForExit)
  If Err.Number <> 0 Then
    AppendLog "WARN: " & cmd & " -> " & Err.Description
    TryRunPython = False
    Exit Function
  End If
  If waitForExit And exitCode <> 0 Then
    AppendLog "ERROR: " & cmd & " exited with code " & exitCode
    TryRunPython = False
    Exit Function
  End If
  AppendLog "OK: " & cmd
  TryRunPython = True
  On Error GoTo 0
End Function

Sub AppendLog(msg)
  Dim stream
  ts = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) & " " & Time
  Set stream = fso.OpenTextFile(logPath, 8, True)
  stream.WriteLine ts & " " & msg
  stream.Close
End Sub
