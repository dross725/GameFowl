' SmartWagers — start print agent with no console window.
' Uses pythonw when available so no black CMD stays open.

Option Explicit
Dim sh, fso, scriptDir, logPath, ts
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
logPath = scriptDir & "\print_agent_silent.log"
sh.CurrentDirectory = scriptDir

If Not fso.FileExists(scriptDir & "\print_agent.py") Then
  AppendLog "ERROR: print_agent.py not found in " & scriptDir
  WScript.Quit 1
End If

' 0 = hidden window, False = do not wait
On Error Resume Next
Err.Clear
sh.Run "pythonw print_agent.py", 0, False
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "pyw print_agent.py", 0, False
End If
If Err.Number <> 0 Then
  Err.Clear
  sh.Run "python print_agent.py", 0, False
End If
If Err.Number <> 0 Then
  AppendLog "ERROR: could not start print agent (" & Err.Description & ")"
  WScript.Quit 1
End If
On Error GoTo 0
WScript.Quit 0

Sub AppendLog(msg)
  Dim stream
  ts = Year(Now) & "-" & Right("0" & Month(Now), 2) & "-" & Right("0" & Day(Now), 2) & " " & Time
  Set stream = fso.OpenTextFile(logPath, 8, True)
  stream.WriteLine ts & " " & msg
  stream.Close
End Sub
