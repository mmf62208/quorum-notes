@echo off
setlocal EnableExtensions
cd /d "%~dp0"
if exist "quorum\" (
  set "ROOT=%cd%"
) else (
  cd /d "%~dp0.."
  if exist "quorum\" (
    set "ROOT=%cd%"
  ) else (
    echo Could not find the Quorum folder. Unzip again so Start Quorum sits next to the quorum folder.
    exit /b 1
  )
)
cd /d "%ROOT%"

set "PY="
where python3 >nul 2>&1 && set "PY=python3"
if not defined PY (
  where py >nul 2>&1 && set "PY=py -3"
)
if not defined PY (
  where python >nul 2>&1 && set "PY=python"
)
if not defined PY (
  echo Quorum needs Python 3.11 or newer. Install Python from python.org, then double-click Start Quorum again.
  exit /b 1
)

%PY% -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 11) else 1)" 2>nul
if errorlevel 1 (
  echo Quorum needs Python 3.11 or newer. Install Python from python.org, then double-click Start Quorum again.
  exit /b 1
)

start "" "http://127.0.0.1:4840"
%PY% -m quorum
exit /b %ERRORLEVEL%
