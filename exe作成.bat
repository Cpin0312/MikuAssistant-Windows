@echo off
chcp 65001 > nul
rem ミクちゃんを1つの exe にまとめる（Python がない PC でも動く）。dist\MikuAssistant\MikuAssistant.exe ができる
cd /d "%~dp0"
py -3 -m pip install pyinstaller pillow
py -3 -m PyInstaller --noconfirm --windowed --name MikuAssistant --icon resources\icon.png --add-data "resources;resources" ミクを起動.pyw
echo.
echo できました：dist\MikuAssistant\MikuAssistant.exe
pause
