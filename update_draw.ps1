# 双色球开奖数据自动更新
# 由计划任务调用：每周一、三、五 09:00（分别覆盖 周日/周二/周四 开奖）
# 流程：抓取四个数据源 -> 重建 CSV/JSON/Excel -> assets/data.js -> 单文件版

$ErrorActionPreference = 'Continue'

$Base = $PSScriptRoot
$Data = Join-Path (Split-Path -Parent $Base) '双色球历史数据'
$LogDir = Join-Path $Base 'logs'
$Stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$RunLog = Join-Path $LogDir ("update-{0}.log" -f $Stamp)
$SumLog = Join-Path $LogDir 'update.log'

$env:PYTHONIOENCODING = 'utf-8'
$env:PYTHONUTF8 = '1'
try { [Console]::OutputEncoding = [System.Text.Encoding]::UTF8 } catch {}

function Write-Log {
  param([string]$Text)
  $line = '[{0}] {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $Text
  Add-Content -LiteralPath $RunLog -Value $line -Encoding UTF8
  Write-Host $line
}

function Get-LatestIssue {
  $p = Join-Path $Base 'assets\data.js'
  if (-not (Test-Path -LiteralPath $p)) { return $null }
  $raw = Get-Content -LiteralPath $p -Raw -Encoding UTF8
  if ($raw -match 'window\.SSQ_RAW\s*=\s*"([^"]+)"') {
    $parts = $matches[1].Split(';')
    $head = $parts[0].Split('|')
    if ($head.Count -ge 2) {
      return [pscustomobject]@{ Code = $head[0]; Date = $head[1]; Count = $parts.Count }
    }
  }
  return $null
}

function Invoke-PyStep {
  param(
    [string]$Label,
    [string]$WorkDir,
    [string]$Script,
    [int]$Retries = 0
  )
  $attempt = 0
  while ($true) {
    $attempt++
    Write-Log ('▶ {0}（第 {1} 次）' -f $Label, $attempt)
    $sw = [Diagnostics.Stopwatch]::StartNew()
    Push-Location -LiteralPath $WorkDir
    try {
      $lines = & $script:Py $Script 2>&1 | ForEach-Object { [string]$_ }
      $code = $LASTEXITCODE
    } finally {
      Pop-Location
    }
    $sw.Stop()
    foreach ($line in $lines) {
      Add-Content -LiteralPath $RunLog -Value ('    ' + $line) -Encoding UTF8
    }
    if ($code -eq 0) {
      Write-Log ('✓ {0} 完成，用时 {1:N1}s' -f $Label, $sw.Elapsed.TotalSeconds)
      return $true
    }
    Write-Log ('✗ {0} 失败，退出码 {1}' -f $Label, $code)
    if ($attempt -gt $Retries) { return $false }
    Write-Log ' 60 秒后重试…'
    Start-Sleep -Seconds 60
  }
}

function Resolve-Python {
  # 探测可用的 python.exe：优先 PATH（python / python3），其次常见安装目录。
  # 命中一个能真正运行的解释器即返回其完整路径；全部落空返回 $null。
  $candidates = @()

  # 1) PATH：解析为具体的 .exe（避免命中别名或 Windows 商店桩）
  foreach ($name in 'python', 'python3') {
    $cmd = Get-Command -Name $name -ErrorAction SilentlyContinue
    if ($cmd -and $cmd.Source) { $candidates += $cmd.Source }
  }

  # 2) 常见安装目录：匹配名为 Python* 的子目录下的 python.exe
  $roots = @()
  if ($env:LOCALAPPDATA)         { $roots += Join-Path $env:LOCALAPPDATA 'Programs\Python' }
  if ($env:ProgramFiles)         { $roots += $env:ProgramFiles }
  if (${env:ProgramFiles(x86)})  { $roots += ${env:ProgramFiles(x86)} }
  $roots += 'C:\'  # 覆盖自建到 C:\PythonNN 这类非默认安装目录的机器

  foreach ($r in $roots) {
    if ([string]::IsNullOrWhiteSpace($r) -or -not (Test-Path -LiteralPath $r)) { continue }
    Get-ChildItem -LiteralPath $r -Directory -ErrorAction SilentlyContinue |
      Where-Object { $_.Name -match 'Python' -and $_.Name -match '\d' } |
      ForEach-Object {
        $exe = Join-Path $_.FullName 'python.exe'
        if (Test-Path -LiteralPath $exe) { $candidates += $exe }
      }
  }

  # 逐个去重并验证可运行（--version 能过），命中即返回
  $seen = [System.Collections.Generic.HashSet[string]]::new([System.StringComparer]::OrdinalIgnoreCase)
  foreach ($c in $candidates) {
    if ($c -and $seen.Add($c) -and (Test-Path -LiteralPath $c)) {
      & $c --version 2>&1 | Out-Null
      if ($LASTEXITCODE -eq 0) { return $c }
    }
  }
  return $null
}

$script:Py = Resolve-Python
if (-not $script:Py) {
  Write-Host '找不到可用的 python.exe，无法更新（已探测 PATH 与常见安装目录）'
  exit 1
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Get-ChildItem -LiteralPath $LogDir -Filter '*.log' -ErrorAction SilentlyContinue |
  Where-Object { $_.LastWriteTime -lt (Get-Date).AddDays(-90) } |
  ForEach-Object { try { [System.IO.File]::Delete($_.FullName) } catch {} }

$startedAt = Get-Date
$before = Get-LatestIssue

Write-Log '===== 双色球开奖数据自动更新 开始 ====='
Write-Log ('主机 {0}\{1} · Python {2}' -f $env:USERDOMAIN, $env:USERNAME, $script:Py)
if ($before) {
  Write-Log ('当前数据：最新 {0} 期（{1}），共 {2} 期' -f $before.Code, $before.Date, $before.Count)
} else {
  Write-Log '当前数据：未找到 assets\data.js'
}

$steps = @(
  [pscustomobject]@{ Label = '抓取四源并生成历史数据（run_all.py）'; Dir = $Data; Script = 'run_all.py'; Retries = 1 },
  [pscustomobject]@{ Label = '生成 assets/data.js（build_data.py）'; Dir = $Base; Script = 'build_data.py'; Retries = 0 },
  [pscustomobject]@{ Label = '重建单文件版（build_single.py）'; Dir = $Base; Script = 'build_single.py'; Retries = 0 }
)

$ok = $true
foreach ($s in $steps) {
  if (-not (Invoke-PyStep -Label $s.Label -WorkDir $s.Dir -Script $s.Script -Retries $s.Retries)) {
    $ok = $false
    break
  }
}

$after = Get-LatestIssue
$elapsed = ((Get-Date) - $startedAt).TotalSeconds
$status = if ($ok) { 'OK' } else { 'FAIL' }

if ($ok) {
  if ($after -and $before -and $after.Code -ne $before.Code) {
    Write-Log ('🎉 新增开奖：{0} -> {1}（{2}），共 {3} 期' -f $before.Code, $after.Code, $after.Date, $after.Count)
  } elseif ($after) {
    Write-Log ('本轮无新增开奖，最新仍为 {0} 期（{1}），共 {2} 期' -f $after.Code, $after.Date, $after.Count)
  }
  Write-Log ('✅ 全部完成，总耗时 {0:N1}s' -f $elapsed)
} else {
  Write-Log ('❌ 更新中止，总耗时 {0:N1}s；详见 {1}' -f $elapsed, $RunLog)
}
Write-Log '===== 结束 ====='

$summary = '{0} | {1} | {2} | {3} 期 | {4:N0}s | {5}' -f `
  (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $status,
  $(if ($after) { $after.Code } else { '-' }),
  $(if ($after) { $after.Count } else { 0 }),
  $elapsed, (Split-Path -Leaf $RunLog)
Add-Content -LiteralPath $SumLog -Value $summary -Encoding UTF8

if ($ok) { exit 0 } else { exit 1 }
