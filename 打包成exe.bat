@echo off
cd /d "%~dp0"
py -3 -m PyInstaller --noconfirm --windowed --onefile --name 作业看台 --icon quill.ico --add-data "quill.ico;." --add-data "update_url.txt;." --clean app.py
if errorlevel 1 exit /b 1
echo Built dist\作业看台.exe
