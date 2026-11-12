@echo off
rem Run the NInfer converter from the repo root it expects.
rem Usage:  run.cmd --model ... --recipe ... --source ... --out ...
setlocal
set "HERE=%~dp0"
set "PY=%NINFER_PYTHON%"
if not defined PY if exist "%HERE%.venv-convert\Scripts\python.exe" set "PY=%HERE%.venv-convert\Scripts\python.exe"
if not defined PY if exist "%HERE%..\ninfer-master\.venv-convert\Scripts\python.exe" set "PY=%HERE%..\ninfer-master\.venv-convert\Scripts\python.exe"
if not defined PY set "PY=python"
echo [ninfer-convert] python: %PY%
pushd "%HERE%ninfer-all-master" || exit /b 1
"%PY%" -m tools.convert %*
set "RC=%ERRORLEVEL%"
popd
exit /b %RC%
