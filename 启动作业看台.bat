@echo off
cd /d "%~dp0"

py -3 -c "import sys" 1>nul 2>nul
if errorlevel 1 goto try_python

py -3 -c "import paramiko" 1>nul 2>nul
if errorlevel 1 (
  echo Installing paramiko ...
  py -3 -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 goto pipfail
)
where pyw >nul 2>nul
if errorlevel 1 (
  py -3 "%~dp0app.py"
) else (
  start "" pyw -3 "%~dp0app.py"
)
exit /b 0

:try_python
python -c "import sys" 1>nul 2>nul
if errorlevel 1 goto nopy
python -c "import paramiko" 1>nul 2>nul
if errorlevel 1 (
  echo Installing paramiko ...
  python -m pip install -r "%~dp0requirements.txt"
  if errorlevel 1 goto pipfail
)
where pythonw >nul 2>nul
if errorlevel 1 (
  python "%~dp0app.py"
) else (
  start "" pythonw "%~dp0app.py"
)
exit /b 0

:nopy
echo Python 3 was not found.
echo Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
exit /b 1

:pipfail
echo Could not install paramiko.
echo In this folder run: py -3 -m pip install -r requirements.txt
pause
exit /b 1
