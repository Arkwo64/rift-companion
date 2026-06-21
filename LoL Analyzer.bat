@echo off
title LoL Analyzer
cd /d "%~dp0"
echo Iniciando LoL Analyzer... (cierra esta ventana para detener la app)
"%LOCALAPPDATA%\Programs\Python\Python312\python.exe" app.py
pause
