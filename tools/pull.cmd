@echo off
rem Hourly pull for Task Scheduler: AHledger pricetables for the tracked houses, and the news.
rem Log: data\pull.log. Register it once with:
rem   schtasks /Create /SC HOURLY /TN "ForeverAH pull" /TR "%~f0" /F
cd /d "%~dp0.."
".venv\Scripts\python.exe" -m pipeline.pull
