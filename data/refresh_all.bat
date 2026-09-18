@echo off
REM Double-click, or run "refresh_all.bat" from cmd, to pull fresh NAV/price
REM data, rebuild every dataset, and update both dashboard pages. Add
REM --prices-only for a quick weekly refresh that skips the (slower) fund
REM universe check, or --no-git to build without committing/pushing.
"C:\Users\Naveen\.conda\envs\hp\python.exe" "%~dp0refresh_all.py" %*
pause
