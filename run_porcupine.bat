@echo off
rem Starts the porcupine without a console window (pythonw instead of python).
cd /d "%~dp0"
start "" pythonw mascot.py
