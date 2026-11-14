Set shell = CreateObject("WScript.Shell")
shell.CurrentDirectory = "D:\Documents\codex\agy plugins mannager\AGY-Launcher"
cmd = "node.exe ""D:\Documents\codex\agy plugins mannager\AGY-Launcher\cli.mjs"" launch"
shell.Run cmd, 0, False
