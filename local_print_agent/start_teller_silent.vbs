' SmartWagers — silent teller startup (no CMD window).
' Starts print agent in background, then opens Chrome to the server.

Option Explicit
Dim sh, fso, scriptDir, batPath, env
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
scriptDir = fso.GetParentFolderName(WScript.ScriptFullName)
batPath = scriptDir & "\start_teller.bat"
Set env = sh.Environment("PROCESS")
env("SMARTWAGERS_SILENT") = "1"
sh.Run """" & batPath & """", 0, False
