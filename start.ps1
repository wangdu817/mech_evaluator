param(
    [ValidateRange(1024, 65535)][int]$Port = 8502,
    [switch]$NoBrowser,
    [switch]$CheckOnly
)
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = New-Object System.Text.UTF8Encoding
Set-Location -LiteralPath $PSScriptRoot
$taskPython = Join-Path $PSScriptRoot '.venv313\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython)) { $taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe' }
if (-not (Test-Path -LiteralPath $taskPython)) { throw '找不到 Python 环境，请先运行 setup.ps1。' }
$env:PYTHONUTF8 = '1'
$env:MPLCONFIGDIR = Join-Path $PSScriptRoot '.cache\matplotlib'
$env:TEMP = Join-Path $PSScriptRoot '.cache\tmp'
$env:TMP = $env:TEMP
foreach ($taskDirectory in @($env:MPLCONFIGDIR, $env:TEMP)) {
    New-Item -ItemType Directory -Path $taskDirectory -Force | Out-Null
}
$taskArguments = @((Join-Path $PSScriptRoot 'tools\launch_ui.py'), '--port', "$Port")
if ($NoBrowser) { $taskArguments += '--no-browser' }
if ($CheckOnly) { $taskArguments += '--check' }
& $taskPython @taskArguments
if ($LASTEXITCODE -ne 0) { throw '启动未成功，请查看上方提示。' }
