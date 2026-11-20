@echo off
chcp 65001 >nul
cd /d "%~dp0"

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$WshShell = New-Object -ComObject WScript.Shell; ^
   $Desktop = [Environment]::GetFolderPath('Desktop'); ^
   $Shortcut = $WshShell.CreateShortcut(\"$Desktop\전시생존 AI챗봇 (오프라인 앱).lnk\"); ^
   $Shortcut.TargetPath = \"%~dp0전시생존_AI챗봇_앱.vbs\"; ^
   $Shortcut.WorkingDirectory = \"%~dp0\"; ^
   $Shortcut.IconLocation = \"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe,0\"; ^
   $Shortcut.Description = \"전시·재난·생존 한·영 통합 AI 챗봇 (인터넷 없이 작동)\"; ^
   $Shortcut.Save()"

echo [완료] 바탕화면에 '전시생존 AI챗봇 (오프라인 앱)' 바로가기 아이콘이 생성되었습니다!
pause
