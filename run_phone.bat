@echo off
rem Starts the phone bot in its own window (close the window to stop it).
cd /d "%~dp0"
start "Porcupine phone bot" cmd /k python phone.py
