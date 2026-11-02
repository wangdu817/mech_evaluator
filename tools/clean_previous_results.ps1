$ErrorActionPreference = 'Stop'
$taskProject = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$taskResults = Join-Path $taskProject 'results'
$taskStage = Join-Path $taskProject '.cache\result-cleanup-preserved'
if ((Resolve-Path -LiteralPath $taskResults).Path -ne $taskResults) { throw 'Unexpected results path' }
if (Test-Path -LiteralPath $taskStage) { throw 'Preservation stage already exists; inspect before retrying' }
if (Get-ChildItem -LiteralPath $taskResults -Recurse -Filter run.lock) { throw 'Run owner lock exists; cleanup refused' }
$taskPreserve = @(
 'ui-state.json', 'ui-run\config.yaml', 'ui-run\prepared',
 'clear-26092002\inputs', 'clear-26092002\prepared', 'clear-26092002\26092002_cantera.yaml',
 'multi-mechanism\inputs', 'multi-mechanism\prepared', 'multi-mechanism\thermo-duplicates.json',
 'source-baseline.json', 'live-snapshot-tests.log'
)
$taskFreeBefore = (Get-PSDrive D).Free
$taskOriginalHashes = @{}
New-Item -ItemType Directory -Path $taskStage | Out-Null
foreach ($taskRelative in $taskPreserve) {
 $taskSource = Join-Path $taskResults $taskRelative
 if (-not (Test-Path -LiteralPath $taskSource)) { continue }
 $taskResolved = (Resolve-Path -LiteralPath $taskSource).Path
 if (-not $taskResolved.StartsWith($taskResults + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Preservation source escaped results' }
 $taskDestination = Join-Path $taskStage $taskRelative
 if (-not $taskDestination.StartsWith($taskStage + '\', [StringComparison]::OrdinalIgnoreCase)) { throw 'Invalid stage destination' }
 foreach ($taskFile in (Get-ChildItem -LiteralPath $taskResolved -Recurse -File)) {
  $taskOriginalHashes[$taskFile.FullName] = (Get-FileHash -LiteralPath $taskFile.FullName -Algorithm SHA256).Hash
 }
 if (Test-Path -LiteralPath $taskResolved -PathType Leaf) {
  $taskOriginalHashes[$taskResolved] = (Get-FileHash -LiteralPath $taskResolved -Algorithm SHA256).Hash
 }
 New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
 Move-Item -LiteralPath $taskResolved -Destination $taskDestination
}
# Exact absolute target checked above; only this project's generated results.
Remove-Item -LiteralPath $taskResults -Recurse -Force
New-Item -ItemType Directory -Path $taskResults | Out-Null
foreach ($taskRelative in $taskPreserve) {
 $taskStaged = Join-Path $taskStage $taskRelative
 if (-not (Test-Path -LiteralPath $taskStaged)) { continue }
 $taskDestination = Join-Path $taskResults $taskRelative
 New-Item -ItemType Directory -Path (Split-Path -Parent $taskDestination) -Force | Out-Null
 Move-Item -LiteralPath $taskStaged -Destination $taskDestination
}
foreach ($taskFile in $taskOriginalHashes.Keys) {
 if ((Get-FileHash -LiteralPath $taskFile -Algorithm SHA256).Hash -ne $taskOriginalHashes[$taskFile]) { throw "Preserved file changed: $taskFile" }
}
Remove-Item -LiteralPath $taskStage -Recurse -Force
$taskFreeAfter = (Get-PSDrive D).Free
$taskReport = [ordered]@{ removed='Historical simulation, analysis, plots, snapshots, saved batches and result selection'; preserved_paths=$taskPreserve; preserved_files=$taskOriginalHashes.Count; hashes_unchanged=$true; free_before=$taskFreeBefore; free_after=$taskFreeAfter; bytes_released=($taskFreeAfter-$taskFreeBefore) }
$taskReport | ConvertTo-Json -Depth 5 | Set-Content -LiteralPath (Join-Path $taskProject 'RESULT_CLEANUP.json') -Encoding utf8
$taskReport | ConvertTo-Json -Depth 5
