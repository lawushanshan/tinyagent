@echo off
chcp 65001 >nul
echo ========================================
echo   Cove Model Router
echo ========================================
echo.

cd /d D:\06llm\llama\llama-b8851-bin-win-cpu-x64
if errorlevel 1 (
    echo [ERROR] cd failed. Check path.
    cmd /k
    exit /b
)

echo Working dir: %CD%
echo.
echo Checking llama-server.exe...
dir llama-server.exe 2>nul
if errorlevel 1 (
    echo [ERROR] llama-server.exe not found!
    cmd /k
    exit /b
)

echo.
echo Checking models.ini...
if not exist "D:\02Personal\gitea\tinyagent\models.ini" (
    echo [ERROR] models.ini not found!
    cmd /k
    exit /b
)

echo.
echo Starting model router on port 8080...
echo.
.\llama-server.exe --models-preset "D:\02Personal\gitea\tinyagent\models.ini" --host 127.0.0.1 --port 8080 --models-max 2
echo.
echo [EXIT] llama-server ended with code %ERRORLEVEL%
cmd /k
