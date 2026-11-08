@echo off
setlocal
rem %~dp0 ends with a backslash; adding a dot avoids the \" escape problem
cd /d "%~dp0."

rem 找一个真的装了 PySide6 的解释器，别用 PATH 里碰巧排在前面的那个
set "PYW="
pythonw -c "import PySide6" >nul 2>&1
if not errorlevel 1 set "PYW=pythonw"
if not defined PYW if exist "C:\Users\m1726\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe" (
    "C:\Users\m1726\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe" -c "import PySide6" >nul 2>&1
    if not errorlevel 1 set "PYW=C:\Users\m1726\.workbuddy\binaries\python\versions\3.13.12\pythonw.exe"
)
if not defined PYW goto nopy

start "" "%PYW%" main.py
exit /b 0

:nopy
echo.
echo   启动失败：当前 Python 里没有 PySide6。
echo.
echo   在你的 Python 里执行一次：
echo       python -m pip install PySide6
echo.
pause
exit /b 1
