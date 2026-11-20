Set WshShell = CreateObject("WScript.Shell")
Set FSO = CreateObject("Scripting.FileSystemObject")
 CurrentDir = FSO.GetParentFolderName(WScript.ScriptFullName)
WshShell.Run """" & CurrentDir & "\전시생존_AI챗봇_앱실행.bat""", 0, False
