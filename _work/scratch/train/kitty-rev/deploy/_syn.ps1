$files = @(
  'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\deploy\v6_s5_fetch.ps1',
  'D:\BaiduNetdiskDownload\Local-AI\train\lines\27b-kittyrev\kitty-rev\deploy\auto_shutdown_guard.ps1'
)
foreach ($f in $files) {
  $tokens = $null; $errors = $null
  $null = [System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$tokens, [ref]$errors)
  $name = Split-Path -Leaf $f
  if ($errors.Count -eq 0) { "$name : PARSE_OK" }
  else { "$name : PARSE_ERRORS -> " + (($errors | ForEach-Object { $_.Message }) -join ' | ') }
}
