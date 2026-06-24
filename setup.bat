@echo off
cd /d "%~dp0"
echo ============================================
echo   Game Terms Extraction - Setup
echo ============================================
echo.

REM -- Step 1: download embedded Python (skip if already present) --
if not exist python\python.exe (
    echo [1/3] Downloading Python 3.11.9 - about 10MB, internet required...
    powershell -Command "Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.11.9/python-3.11.9-embed-amd64.zip' -OutFile 'python_embed.zip' -UseBasicParsing"
    if errorlevel 1 (
        echo Download failed. Check your internet connection.
        pause & exit /b 1
    )
    echo Extracting...
    powershell -Command "Expand-Archive -Path 'python_embed.zip' -DestinationPath 'python' -Force"
    del python_embed.zip
)

REM -- Step 1b: enable site-packages. Wildcard *.pth does NOT match python311._pth --
powershell -Command "Get-ChildItem 'python\python*._pth' | ForEach-Object { (Get-Content $_) -replace '#import site','import site' | Set-Content $_ -Encoding Ascii }"

REM -- Step 2: ensure pip is importable. Self-heals a half-finished install --
python\python.exe -m pip --version >nul 2>&1
if errorlevel 1 (
    echo Installing pip...
    powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'get_pip.py' -UseBasicParsing"
    python\python.exe get_pip.py --quiet
    del get_pip.py
)

REM -- Step 3: install dependencies --
echo.
echo [2/3] Installing dependencies...
python\python.exe -m pip install -r requirements.txt -q
if errorlevel 1 (
    echo Dependency install failed.
    pause & exit /b 1
)

echo.
echo ============================================
echo   Setup complete! Double-click run.bat to launch.
echo ============================================
echo.
pause
