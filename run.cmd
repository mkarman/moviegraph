@echo off
rem Double-click to build your movie graph: copies the newest Amazon and Netflix exports from Downloads,
rem asks for your TMDB key the first time, runs the pipeline and opens the graph. Extra arguments pass through.
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (py -3 scripts\run_pipeline.py --import %*) else (python scripts\run_pipeline.py --import %*)
echo.
pause
