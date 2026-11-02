' Starts Jarvis without a console window. Use the tray icon to pause or quit;
' the tray's "Open log" shows what the console would have.
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
sh.Environment("Process")("JARVIS_HIDDEN") = "1"
sh.Run "cmd /c """ & here & "\start-jarvis.cmd""", 0, False
