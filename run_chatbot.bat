@echo off
chcp 65001 >nul
cd /d "%~dp0"

if exist ".venv\Scripts\streamlit.exe" (
    echo [실행] 전시·재난 생존매뉴얼 한·영 통합 RAG 챗봇(Streamlit)을 시작합니다...
    ".venv\Scripts\streamlit.exe" run app.py
    pause
    exit /b
)

if exist "C:\Users\6250h\Desktop\chatbot\.venv\Scripts\streamlit.exe" (
    echo [실행] 기존 가상환경을 사용하여 전시·재난 생존매뉴얼 한·영 통합 RAG 챗봇(Streamlit)을 시작합니다...
    "C:\Users\6250h\Desktop\chatbot\.venv\Scripts\streamlit.exe" run app.py
    pause
    exit /b
)

echo [안내] 가상환경(.venv) 및 패키지를 설치합니다...
"C:\Users\6250h\.local\bin\uv.exe" venv --python 3.12 .venv
"C:\Users\6250h\.local\bin\uv.exe" pip install --python .venv\Scripts\python.exe -r requirements.txt
".venv\Scripts\streamlit.exe" run app.py
pause
