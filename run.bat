@echo off
cd /d "%~dp0"
python -m forum_clone.clone %*
pause
