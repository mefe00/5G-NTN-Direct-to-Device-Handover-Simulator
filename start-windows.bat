@echo off
REM 5G-NTN Disaster Handover Simulator - Windows Baslatici
REM Cift tiklayarak veya komut satirindan calistirin

title 5G-NTN Simulator

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [HATA] Python bulunamadi.
    echo Lutfen https://www.python.org/downloads/ adresinden Python 3.10+ kurun.
    echo Kurulum sirasinda "Add Python to PATH" secenegini isaretleyin.
    pause
    exit /b 1
)

python run.py %*

pause
