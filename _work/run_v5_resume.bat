@echo off
REM 2B 门控 v5 续训：从 checkpoint-1600 恢复（DSH 崩溃导致训练进程被杀，损失 188 步）
REM 关键：用独立进程启动，脱离 DSH 进程树 —— DSH 再崩不影响训练
cd /d D:\BaiduNetdiskDownload\Local-AI

set PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
set VRAM_FRAC=0.93
set PYTHONIOENCODING=utf-8
set HF_HUB_OFFLINE=1
set OMP_NUM_THREADS=6
set MKL_NUM_THREADS=6

echo [%date% %time%] ================ 2B v5 续训启动 ================ >> train\logs\2b-v5-resume.log
echo [%date% %time%] resume=out\2b-nsfw-v5\checkpoint-1600  out=out\2b-nsfw-v5 >> train\logs\2b-v5-resume.log

train\.venv\Scripts\python.exe -u train\lines\_shared\scripts\train_qlora9b.py ^
  --base train\lines\9b-oxcoder\models\OxCoder-9B ^
  --data train\lines\9b-oxcoder\data\nsfw-gated\train-2b-gated-v5.jsonl ^
  --stage nsfw ^
  --resume train\lines\9b-oxcoder\out\2b-nsfw-v5\checkpoint-1600 ^
  --out train\lines\9b-oxcoder\out\2b-nsfw-v5 ^
  --ctx 2048 --epochs 1 --lr 2e-5 --ga 4 --bs 1 --seed 42 ^
  --lora-r 32 --lora-alpha 64 --lora-dropout 0.1 --weight-decay 0.01 ^
  --optim adamw_torch --use-liger-ce ^
  --save-steps 400 --save-total-limit 8 >> train\logs\2b-v5-resume-train.log 2>&1

echo [%date% %time%] 训练退出 rc=%ERRORLEVEL% >> train\logs\2b-v5-resume.log

REM 训练结束后自动跑分片门控评测
if exist train\lines\9b-oxcoder\out\2b-nsfw-v5\final (
  echo [%date% %time%] final 已生成，开始分片门控评测 >> train\logs\2b-v5-resume.log
  bash train/lines/9b-oxcoder/_gate_shard.sh train/lines/9b-oxcoder/out/2b-nsfw-v5/final v5 12 >> train\logs\2b-v5-resume.log 2>&1
  echo [%date% %time%] 评测退出 rc=%ERRORLEVEL% >> train\logs\2b-v5-resume.log
)
