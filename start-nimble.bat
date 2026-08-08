@echo off
REM ---------------------------------------------------------------------------
REM Nimble Lab Manager launcher (Windows -> WSL)
REM Starts the FastAPI server inside WSL, waits until it answers, then opens the
REM app in your default browser. Close the "server" window to stop the app.
REM ---------------------------------------------------------------------------
title Nimble Lab Manager (launcher)
echo Starting Nimble Lab Manager...
echo.

REM Start the server in its own WSL window. That window shows the server log and
REM stays open while the app runs; closing it stops the server.
REM The repo directory comes from this script's own location (%~dp0), converted
REM to a WSL path, so the launcher works wherever the repo has been cloned.
set "HERE=%~dp0"
if "%HERE:~-1%"=="\" set "HERE=%HERE:~0,-1%"
start "Nimble Lab Manager - server (close to stop)" wsl.exe -e bash -lc "cd \"$(wslpath -a '%HERE%')\" && python3 run.py"

REM Poll the server until it responds (up to ~30s), then open the browser.
set /a tries=0
:waitloop
timeout /t 1 /nobreak >NUL
curl -s -o NUL http://127.0.0.1:8770/ && goto ready
set /a tries+=1
if %tries% geq 30 goto timedout
goto waitloop

:ready
start "" http://127.0.0.1:8770/
exit /b 0

:timedout
echo.
echo The server did not respond on http://127.0.0.1:8770 within 30 seconds.
echo Check the server window for errors, then try again.
echo.
pause
exit /b 1
