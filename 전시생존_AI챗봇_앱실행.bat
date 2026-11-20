@echo off
chcp 65001 >nul
cd /d "%~dp0"

set "APP_URL=file:///%~dp0index.html"
set "APP_URL=%APP_URL:\=/%"

:: 1. Microsoft Edge 앱 모드(주소창/탭 없는 독립 데스크톱 앱 창)로 실행
if exist "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe" --app="%APP_URL%" --window-size=1280,860
    exit /b
)
if exist "C:\Program Files\Microsoft\Edge\Application\msedge.exe" (
    start "" "C:\Program Files\Microsoft\Edge\Application\msedge.exe" --app="%APP_URL%" --window-size=1280,860
    exit /b
)

:: 2. Google Chrome 앱 모드로 실행
if exist "C:\Program Files\Google\Chrome\Application\chrome.exe" (
    start "" "C:\Program Files\Google\Chrome\Application\chrome.exe" --app="%APP_URL%" --window-size=1280,860
    exit /b
)

:: 3. 기본 브라우저로 실행
start "" "%~dp0index.html"
