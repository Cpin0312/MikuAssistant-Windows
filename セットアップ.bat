@echo off
chcp 65001 > nul
rem ミクちゃん（Windows 版）に必要な部品を入れる。最初に1回だけダブルクリック
cd /d "%~dp0"
py -3 -m pip install --upgrade pip
py -3 -m pip install -r requirements.txt
echo.
echo 準備ができました。「ミクを起動.pyw」をダブルクリックしてね
pause
