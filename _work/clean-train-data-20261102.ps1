# 训练数据清理 · 2026-11-02 · 只删可重建的旧世代数据集与派生副本
# 保留：gen3_1p6(P1对应) · gen7-nsfw-kitty · gen7-text · gen8-* · traj/cont 血缘件 · 9B 全线不动
$ErrorActionPreference = 'Stop'
$R = 'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\data'
$V = Join-Path $R 'versions'

$targets = @()

# A 旧审计目录（626.7 MiB）：被清理前的旧版副本 + offenders，全部被 gen8 取代
$targets += Join-Path $R 'audit-20261101-191515'

# B 旧世代 gen2 / gen3（除 gen3_1p6）
$oldGen = @(
  'gen2-nsfw-kitty.20261029-003831.jsonl',
  'gen2-nsfw-kitty-v2.20261029-124315.jsonl',
  'gen3-nsfw-kitty.20261030-003024.jsonl',
  'gen3_1-nsfw-kitty.20261030-155110.jsonl',
  'gen3_1x3-nsfw-kitty.20261030-160940.jsonl',
  'gen3_1p-nsfw-kitty.20261101-022516.jsonl',
  'gen3_1p2-nsfw-kitty.jsonl',
  'gen3_1p3-nsfw-kitty.jsonl',
  'gen3_1p3-nsfw-kittyx2.jsonl',
  'gen3_1p4-nsfw-kitty.jsonl',
  'gen3_1p5-nsfw-kitty.jsonl'
)

# C gen4 / gen5 / gen6 全支（已被 gen7/gen8 取代）
$midGen = @(
  'gen4-nsfw-kitty.jsonl','gen4-text.jsonl','gen4-gate.jsonl','gen4-cont.jsonl','gen4-traj-raw.jsonl',
  'gen5-nsfw-kitty.jsonl','gen5-text.jsonl','gen5-gate.jsonl','gen5-cont.jsonl','gen5-traj-raw.jsonl',
  'gen6-nsfw-kitty.jsonl','gen6-text.jsonl','gen6-traj-raw.jsonl',
  'gen7-gate.jsonl'
)

# D 与 _shared/data/nsfw 哈希一致的重复副本 + 最早的手打包派生件
$dups = @(
  'nsfw-train-cont.20261027-203028.jsonl',
  'nsfw-train-scene.20261027-203028.jsonl',
  'nsfw-train-multi.20261027-203028.jsonl',
  'nsfw-train-style.20261027-203028.jsonl',
  'nsfw-train-expand.20261027-203028.jsonl',
  'nsfw-nsfw-lexicon-v9.20261027-203028.json',
  'nsfw-nsfw-glossary-merged.20261027-203028.jsonl',
  'final-joint.20261027-022747.jsonl',
  'final-nsfw.20261027-022747.jsonl',
  'final-re.20261027-022747.jsonl',
  'mix-re.20261027-011850.jsonl'
)

foreach ($n in ($oldGen + $midGen + $dups)) {
  $targets += Join-Path $V $n
  $targets += Join-Path $V ($n + '.sha256')
}

$before = (Get-PSDrive D).Free
$freed = 0
$deleted = 0
foreach ($t in $targets) {
  if (Test-Path $t) {
    $sz = (Get-ChildItem $t -Recurse -File -ErrorAction SilentlyContinue | Measure-Object Length -Sum).Sum
    if ($null -eq $sz) { $sz = (Get-Item $t).Length }
    Remove-Item $t -Recurse -Force
    $freed += $sz; $deleted++
    'DEL {0,10:N1} MiB  {1}' -f ($sz/1MB), $t.Replace($R,'data')
  }
}
$after = (Get-PSDrive D).Free
'---'
'deleted={0}  freed={1:N2} GiB  D free: {2:N1} -> {3:N1} GB' -f $deleted, ($freed/1GB), ($before/1GB), ($after/1GB)
