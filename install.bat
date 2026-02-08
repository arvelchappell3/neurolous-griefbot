@echo off
REM ============================================================================
REM  Neurolous Open Source Agent — Windows Installer
REM  Run this from Command Prompt or PowerShell
REM ============================================================================

setlocal enabledelayedexpansion
title Neurolous Installer

echo.
echo   _   _                      _
echo  ^| \ ^| ^| ___ _   _ _ __ ___ ^| ^| ___  _   _ ___
echo  ^|  \^| ^|/ _ \ ^| ^| ^| '__/ _ \^| ^|/ _ \^| ^| ^| / __^|
echo  ^| ^|\  ^|  __/ ^|_^| ^| ^| ^| (_) ^| ^| (_) ^| ^|_^| \__ \
echo  ^|_^| \_^|\___^|\__,_^|_^|  \___/^|_^|\___/ \__,_^|___/
echo.
echo   Open Source Agent — Windows Installer
echo.
echo ========================================================
echo.

REM --- Detect architecture ---
echo [INFO]  Detected OS: Windows
if "%PROCESSOR_ARCHITECTURE%"=="AMD64" (
    echo [INFO]  Detected Architecture: x86_64
) else (
    echo [INFO]  Detected Architecture: %PROCESSOR_ARCHITECTURE%
)
echo.
echo ========================================================
echo.

REM --- Check Python ---
echo [INFO]  Checking for Python 3.10+ ...
python --version >nul 2>&1
if errorlevel 1 (
    python3 --version >nul 2>&1
    if errorlevel 1 (
        echo [FAIL]  Python 3.10+ is not installed.
        echo         Download it from: https://www.python.org/downloads/
        echo         IMPORTANT: Check "Add Python to PATH" during installation.
        echo.
        pause
        exit /b 1
    ) else (
        set PYTHON_CMD=python3
    )
) else (
    set PYTHON_CMD=python
)

for /f "tokens=2 delims= " %%v in ('%PYTHON_CMD% --version 2^>^&1') do set PY_VER=%%v
echo [OK]    Python found: %PY_VER%

REM --- Check Ollama ---
echo [INFO]  Checking for Ollama ...
ollama --version >nul 2>&1
if errorlevel 1 (
    echo [FAIL]  Ollama is not installed.
    echo         Download it from: https://ollama.ai/download
    echo         Install it and re-run this script.
    echo.
    pause
    exit /b 1
)
echo [OK]    Ollama found.

REM --- Start Ollama if not running ---
echo [INFO]  Ensuring Ollama is running...
curl -sf http://localhost:11434/api/tags >nul 2>&1
if errorlevel 1 (
    echo [INFO]  Starting Ollama in the background...
    start /B ollama serve >nul 2>&1
    timeout /t 5 /nobreak >nul

    curl -sf http://localhost:11434/api/tags >nul 2>&1
    if errorlevel 1 (
        echo [WARN]  Waiting for Ollama to start...
        timeout /t 10 /nobreak >nul
        curl -sf http://localhost:11434/api/tags >nul 2>&1
        if errorlevel 1 (
            echo [FAIL]  Ollama did not start. Try running "ollama serve" manually.
            pause
            exit /b 1
        )
    )
)
echo [OK]    Ollama is running.

REM --- Pull models ---
echo [INFO]  Checking required Ollama models...

ollama list 2>nul | findstr /i "gemma3" >nul 2>&1
if errorlevel 1 (
    echo [INFO]  Pulling model: gemma3:4b-it-qat (this may take a few minutes)...
    ollama pull gemma3:4b-it-qat
) else (
    echo [OK]    Model already pulled: gemma3:4b-it-qat
)

ollama list 2>nul | findstr /i "nomic-embed-text" >nul 2>&1
if errorlevel 1 (
    echo [INFO]  Pulling model: nomic-embed-text (this may take a few minutes)...
    ollama pull nomic-embed-text
) else (
    echo [OK]    Model already pulled: nomic-embed-text
)

echo.
echo ========================================================
echo.

REM --- Set up virtual environment ---
set SCRIPT_DIR=%~dp0
set BACKEND_DIR=%SCRIPT_DIR%backend

if not exist "%BACKEND_DIR%" (
    echo [FAIL]  Backend directory not found at %BACKEND_DIR%
    pause
    exit /b 1
)

echo [INFO]  Setting up Python virtual environment...

if not exist "%BACKEND_DIR%\venv" (
    %PYTHON_CMD% -m venv "%BACKEND_DIR%\venv"
    echo [OK]    Virtual environment created.
) else (
    echo [OK]    Virtual environment already exists.
)

call "%BACKEND_DIR%\venv\Scripts\activate.bat"

echo [INFO]  Installing Python dependencies (this may take several minutes on first run)...
pip install --upgrade pip --quiet
pip install -r "%BACKEND_DIR%\requirements.txt" --quiet
echo [OK]    All Python dependencies installed.

echo.
echo ========================================================
echo.

REM --- Ensure persona config ---
if not exist "%BACKEND_DIR%\config\persona.json" (
    if exist "%BACKEND_DIR%\config\persona.example.json" (
        copy "%BACKEND_DIR%\config\persona.example.json" "%BACKEND_DIR%\config\persona.json" >nul
        echo [INFO]  Created persona.json from example template.
    ) else (
        echo [WARN]  No persona.json found. Configure via Admin at http://localhost:8000/admin
    )
) else (
    echo [OK]    Persona config found.
)

echo.
echo ========================================================
echo.
echo   [OK]  Setup complete! Launching Neurolous...
echo.
echo ========================================================
echo.
echo [INFO]  Starting FastAPI backend on http://localhost:8000 ...
echo [INFO]  Press Ctrl+C to stop the server.
echo.

REM --- Open browser after a short delay ---
start /B cmd /c "timeout /t 3 /nobreak >nul && start http://localhost:8000"

REM --- Start backend ---
cd /d "%BACKEND_DIR%"
%PYTHON_CMD% main.py

endlocal
