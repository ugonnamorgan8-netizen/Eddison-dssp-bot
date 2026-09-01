
' DSSP Automation — Silent Dashboard Starter
' Runs dashboard.py in the background with no console window.

Dim shell
Set shell = CreateObject("WScript.Shell")

Dim projectDir
projectDir = "c:\Users\LENOVO\Desktop\DSSP Automation"

shell.CurrentDirectory = projectDir
shell.Run "python dashboard.py", 0, False

Set shell = Nothing
