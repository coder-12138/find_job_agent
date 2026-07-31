@echo off
setlocal
cd /d "%~dp0"

set "PYTHON_EXE=%CD%\.venv\Scripts\python.exe"

if exist "%PYTHON_EXE%" goto run_server

echo.
echo ERROR: Project virtual environment was not found.
echo Expected file:
echo %PYTHON_EXE%
echo.
echo Install the project dependencies first, then run this file again.
echo.
pause
exit /b 1

:run_server
set "PYTHONPATH=%CD%\src"
set "JOB_AGENT_BROWSER_HEADLESS=0"

echo.
echo ========================================
echo Job Application Assistant
echo ========================================
echo.
echo Open this URL in your browser:
echo http://127.0.0.1:8000/
echo.
echo Keep this window open while using the app.
echo Press Ctrl+C or close this window to stop the server.
echo.

"%PYTHON_EXE%" -m uvicorn job_application_agent_langchain.web.app:app --host 127.0.0.1 --port 8000

if not errorlevel 1 goto finished

echo.
echo ERROR: The server stopped unexpectedly.
echo Review the error message above.
echo.
pause

:finished
endlocal
