@echo off
rem FM27 Press Voice yan uygulamasi. Ornek: start.bat  |  start.bat --text  |  start.bat sim  |  start.bat check
cd /d "%~dp0"
chcp 65001 >nul
title FM27 Basin Modu
"%~dp0.venv\Scripts\python.exe" -X utf8 "%~dp0main.py" %*
