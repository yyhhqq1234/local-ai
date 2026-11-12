@echo off
REM ============================================================================
REM  OxCoder-9B / 任意 Qwen3.5-9B 类检查点 -> .ninfer
REM  用法（先改下面 3 个路径）：
REM      set SRC=D:\...\OrionLLM\OxCoder-9B          （HF safetensors 目录）
REM      set META=D:\...\metadata-oxcoder9b          （只要 config/tokenizer 等元数据）
REM      convert-oxcoder9b.cmd
REM  无参 = 转换；传 q8max 作第 1 参数 = 全 Q8 高质量档
REM ============================================================================
setlocal

set ROOT=D:\BaiduNetdiskDownload\Local-AI
set CONV=%ROOT%\train\tools\ninfer-convert
set PY=%ROOT%\train\tools\ninfer-master\.venv-convert\Scripts\python.exe

REM ---- 改这三个 ----
set SRC=%ROOT%\train\models\OxCoder-9B
set META=%ROOT%\train\models\metadata-oxcoder9b
set OUT=%ROOT%\train\models\oxcoder-9b-Q4Q5.ninfer
REM ------------------

set RECIPE=qwen3_5_9b
if /I "%~1"=="q8max" set RECIPE=qwen3_5_9b_q8max
if /I "%~1"=="q8max" set OUT=%ROOT%\train\models\oxcoder-9b-Q8max.ninfer

if not exist "%PY%" ( echo [ERR] venv python missing: %PY% & exit /b 2 )
if not exist "%SRC%\config.json" ( echo [ERR] config.json missing under %SRC% & exit /b 3 )
if not exist "%META%\generation_config.json" ( echo [ERR] generation_config.json missing under %META% & exit /b 4 )
if not exist "%META%\tokenizer.json" ( echo [ERR] tokenizer.json missing under %META% & exit /b 5 )

echo [1/2] recipe = %RECIPE%
echo [2/2] out     = %OUT%
echo.

pushd "%CONV%\ninfer-all-master"
"%PY%" -m tools.convert ^
  --model   "%META%" ^
  --recipe  %RECIPE% ^
  --source  quantized="%SRC%" ^
  --components text ^
  --device cpu ^
  --rows-per-chunk 512 ^
  --name "oxcoder-9b" ^
  --out  "%OUT%"
set RC=%ERRORLEVEL%
popd

if %RC% NEQ 0 ( echo. & echo [FAIL] convert exit=%RC% & exit /b %RC% )
echo.
echo [OK] %OUT%
exit /b 0
