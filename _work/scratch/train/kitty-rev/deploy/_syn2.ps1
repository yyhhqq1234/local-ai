$f = 'D:\BaiduNetdiskDownload\Local-AI\train\kitty-rev\deploy\v6_s6_retest.ps1'
$tokens = $null; $errors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile($f, [ref]$tokens, [ref]$errors)
if ($errors.Count -eq 0) { 'v6_s6_retest.ps1 : PARSE_OK' }
else { 'PARSE_ERRORS -> ' + (($errors | ForEach-Object { $_.Message }) -join ' | ') }
